#!/usr/bin/env python3
"""Mantém o site da Cassandra no Netlify apontando para o túnel atual do Pi.

A URL do quick tunnel da Cloudflare muda a cada reinício (reboot, queda). Este script roda como serviço
(cassandra-netlify-sync) e, a cada 30 s, confere a URL atual do túnel e a página (HTML_PAGE do web_server.py, com o kit de personagens embutido).
Se alguma mudou desde a última publicação, publica de novo pela API do Netlify: index.html + _redirects
(/api/* -> túnel). Só a biblioteca padrão do Python; nada para instalar.

Também é o VIGIA do túnel: o quick tunnel não tem garantia de ficar no ar — a Cloudflare às vezes o apaga, e o
cloudflared não sai (fica tentando para sempre "Tunnel not found"), então o Restart=always do systemd não ajuda.
A cada ciclo, se o log do túnel mostra que ele morreu, ou se o endereço público falha várias vezes seguidas enquanto
a Cassandra responde em localhost, reinicia o serviço cassandra-tunnel; a URL nova é publicada no ciclo seguinte.
E se a própria Cassandra parar de responder em localhost:8080 por uns 5 minutos (travada — se ela cair, o systemd já
a reinicia), reinicia o cassandra-assistant.

Configuração em ~/.config/cassandra/netlify.env (chmod 600):
  NETLIFY_AUTH_TOKEN=...   (token pessoal: Netlify > User settings > Applications > Personal access tokens)
  NETLIFY_SITE_ID=...
Uso manual: cassandra-netlify-sync.py --once   (publica agora se precisar e sai)
"""
import ast
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HOME = Path.home()
CONFIG = HOME / ".config/cassandra/netlify.env"
STATE = HOME / ".local/state/cassandra/netlify-sync.json"
WEB_SERVER = HOME / "Desktop/personal-assistant/web_server.py"
PERSONA_JS = HOME / "Desktop/personal-assistant/cassandra/web/persona.js"
TUNNEL_LOG = Path("/tmp/cloudflared.log")
TUNNEL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
API = "https://api.netlify.com/api/v1"
INTERVAL = 30
LOCAL = "http://localhost:8080/"
DEAD_RE = re.compile(r"Tunnel not found|tunnel.*(?:deleted|does not exist)", re.IGNORECASE)
PROBE_FAILS = 4          # falhas seguidas do endereço público (com o local ok) antes de reiniciar: ~2 min
RESTART_GRACE = 120      # depois de reiniciar, espera o túnel novo registrar antes de julgar de novo
RESTART_MIN_GAP = 300    # e nunca reinicia mais que uma vez a cada 5 min (a Cloudflare limita túneis novos)
LOCAL_FAILS = 10         # ciclos seguidos sem a Cassandra responder em localhost (~5 min) antes de reiniciá-la
APP_MIN_GAP = 900        # no máximo um reinício dela a cada 15 min (subir leva até ~1 min)


def log(msg):
    print(f"[netlify-sync {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_config():
    cfg = {}
    for line in CONFIG.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    return cfg["NETLIFY_AUTH_TOKEN"], cfg["NETLIFY_SITE_ID"]


def tunnel_url():
    try:
        m = TUNNEL_RE.search(TUNNEL_LOG.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return None
    return m.group(0) if m else None


def persona_script():
    """O kit de personagens (rosto e cores) que o web_server.py embute na página ao servir — a mesma troca daqui."""
    try:
        js = PERSONA_JS.read_text(encoding="utf-8").replace("</script", "<\\/script")
    except OSError:
        js = "window.AgentPersona={face:function(){return ''},mount:function(){}};"
    return "<script>" + js + "</script>"


def html_page():
    src = WEB_SERVER.read_text(encoding="utf-8")
    for node in ast.parse(src).body:
        # A primeira atribuição é a página em si; a seguinte (HTML_PAGE = HTML_PAGE.replace(...)) embute o kit de
        # personagens, e é refeita aqui — sem isso o site ia sem o rosto da Cassandra.
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                and any(getattr(t, "id", None) == "HTML_PAGE" for t in node.targets)):
            return ast.literal_eval(node.value).replace("<!--PERSONA_JS-->", persona_script(), 1)
    raise RuntimeError("HTML_PAGE não encontrado no web_server.py")


def api(method, path, token, body=None, content_type="application/json"):
    data = json.dumps(body).encode() if content_type == "application/json" and body is not None else body
    req = urllib.request.Request(f"{API}{path}", data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "Content-Type": content_type, "User-Agent": "cassandra-netlify-sync"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


def deploy(token, site_id, url, html):
    files = {
        "/index.html": html.encode("utf-8"),
        "/_redirects": f"/api/*  {url}/api/:splat  200!\n".encode("utf-8"),
    }
    digests = {path: hashlib.sha1(data).hexdigest() for path, data in files.items()}
    d = api("POST", f"/sites/{site_id}/deploys", token, {"files": digests})
    need = set(d.get("required") or [])
    for path, data in files.items():
        if digests[path] in need:
            api("PUT", f"/deploys/{d['id']}/files{path}", token, data, "application/octet-stream")
    for _ in range(60):  # espera ficar pronto (normalmente poucos segundos)
        state = api("GET", f"/deploys/{d['id']}", token).get("state")
        if state == "ready":
            return
        if state == "error":
            raise RuntimeError("o Netlify recusou o deploy")
        time.sleep(2)
    raise RuntimeError("deploy não ficou pronto a tempo")


def sync_once(token, site_id):
    url = tunnel_url()
    if not url:
        return False
    html = html_page()
    want = {"url": url, "html": hashlib.sha1(html.encode("utf-8")).hexdigest()}
    try:
        have = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        have = {}
    if have == want:
        return False
    reason = "túnel novo" if have.get("url") != url else "página mudou"
    log(f"publicando ({reason}): {url}")
    deploy(token, site_id, url, html)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(want), encoding="utf-8")
    log("site atualizado.")
    return True


def _ok(url, timeout=15):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "cassandra-tunnel-watch"}),
                                    timeout=timeout) as r:
            return 200 <= r.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500 and e.code not in (404,)  # 530/502/404 da Cloudflare = túnel fora
    except Exception:  # noqa: BLE001 — DNS, timeout, conexão recusada
        return False


class TunnelWatch:
    """Decide quando o túnel morreu (ou a Cassandra travou) e reinicia o serviço."""

    def __init__(self):
        self.fails = 0
        self.last_restart = 0.0
        self.local_fails = 0
        self.last_app_restart = time.monotonic()  # o serviço acabou de subir junto: dá tempo à Cassandra

    def _restart(self, unit):
        try:
            subprocess.run(["systemctl", "--user", "restart", unit], check=True, timeout=90)
        except Exception as e:  # noqa: BLE001
            log(f"não consegui reiniciar {unit}: {e}")

    def local_down(self, now):
        """A Cassandra não respondeu em localhost: conta, e a reinicia se ficar travada tempo demais."""
        self.fails = 0  # com ela fora, reiniciar o túnel não resolve
        self.local_fails += 1
        if self.local_fails == 1:
            log("a Cassandra não responde em localhost:8080.")
        if self.local_fails >= LOCAL_FAILS and now - self.last_app_restart >= APP_MIN_GAP:
            log(f"a Cassandra não responde há {self.local_fails} ciclos: reiniciando o cassandra-assistant.")
            self.last_app_restart, self.local_fails = now, 0
            self._restart("cassandra-assistant")

    def dead_in_log(self):
        """O log diz que a Cloudflare apagou o túnel — depois da última conexão registrada."""
        try:
            text = TUNNEL_LOG.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return False
        tail = text[text.rfind("Registered tunnel connection"):] if "Registered tunnel connection" in text else text
        return bool(DEAD_RE.search(tail))

    def check(self):
        now = time.monotonic()
        if _ok(LOCAL, timeout=10):
            if self.local_fails:
                log("a Cassandra voltou a responder em localhost:8080.")
            self.local_fails = 0
        else:
            self.local_down(now)
            return
        if now - self.last_restart < RESTART_GRACE:
            return
        url = tunnel_url()
        reason = ""
        if self.dead_in_log():
            reason = "a Cloudflare apagou o túnel (Tunnel not found)"
        elif url:
            if _ok(url + "/"):
                self.fails = 0
            else:  # a Cassandra está de pé (conferido acima): o problema é o túnel
                self.fails += 1
                if self.fails >= PROBE_FAILS:
                    reason = f"o endereço público falhou {self.fails} vezes seguidas"
        if not reason:
            return
        if self.last_restart and now - self.last_restart < RESTART_MIN_GAP:
            log(f"túnel fora ({reason}), mas reiniciei há pouco; espero.")
            return
        log(f"reiniciando o túnel: {reason}.")
        self.last_restart, self.fails = now, 0
        self._restart("cassandra-tunnel")


def main():
    if not CONFIG.exists():
        sys.exit(f"Falta {CONFIG} com NETLIFY_AUTH_TOKEN e NETLIFY_SITE_ID.")
    token, site_id = load_config()
    once = "--once" in sys.argv
    watch = TunnelWatch()
    while True:
        if not once:
            try:
                watch.check()
            except Exception as e:  # noqa: BLE001
                log(f"erro no vigia do túnel: {e}")
        try:
            sync_once(token, site_id)
        except urllib.error.HTTPError as e:
            log(f"erro da API do Netlify: HTTP {e.code} {e.read()[:200]!r}")
            if once:
                sys.exit(1)
        except Exception as e:  # noqa: BLE001 — rede caída etc.: tenta de novo no próximo ciclo
            log(f"erro: {e}")
            if once:
                sys.exit(1)
        if once:
            return
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
