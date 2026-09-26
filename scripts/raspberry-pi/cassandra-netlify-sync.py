#!/usr/bin/env python3
"""Mantém o site da Cassandra no Netlify apontando para o túnel atual do Pi.

A URL do quick tunnel da Cloudflare muda a cada reinício (reboot, queda). Este script roda como serviço
(cassandra-netlify-sync) e, a cada 30 s, confere a URL atual do túnel e a página (HTML_PAGE do web_server.py).
Se alguma mudou desde a última publicação, publica de novo pela API do Netlify: index.html + _redirects
(/api/* -> túnel). Só a biblioteca padrão do Python; nada para instalar.

Configuração em ~/.config/cassandra/netlify.env (chmod 600):
  NETLIFY_AUTH_TOKEN=...   (token pessoal: Netlify > User settings > Applications > Personal access tokens)
  NETLIFY_SITE_ID=...
Uso manual: cassandra-netlify-sync.py --once   (publica agora se precisar e sai)
"""
import ast
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HOME = Path.home()
CONFIG = HOME / ".config/cassandra/netlify.env"
STATE = HOME / ".local/state/cassandra/netlify-sync.json"
WEB_SERVER = HOME / "Desktop/personal-assistant/web_server.py"
TUNNEL_LOG = Path("/tmp/cloudflared.log")
TUNNEL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
API = "https://api.netlify.com/api/v1"
INTERVAL = 30


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


def html_page():
    src = WEB_SERVER.read_text(encoding="utf-8")
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "HTML_PAGE" for t in node.targets):
            return ast.literal_eval(node.value)
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


def main():
    if not CONFIG.exists():
        sys.exit(f"Falta {CONFIG} com NETLIFY_AUTH_TOKEN e NETLIFY_SITE_ID.")
    token, site_id = load_config()
    once = "--once" in sys.argv
    while True:
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
