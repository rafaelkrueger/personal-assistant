"""Os agentes pessoais — Pulse (saúde), Cifra (finanças), Torque (carro) — falados DIRETO pela Cassandra.

A regra do sistema é que nenhum agente chama outro: a ponte é o Maestro. A Cassandra é a exceção, e só para os
agentes pessoais: ela é a "maestra" deles. Guarda aqui a documentação de cada um (Docs/agents/<nome>/, cópia do
CAPABILITIES.md e do API.md do agente — sincronizada por orchestrator/plugin/sync_copies.py) e fala com eles por
HTTP, sem passar pelo Maestro. Assim os agentes pessoais continuam funcionando com o computador desligado (os que
moram no Raspberry Pi) e a conversa não depende de dois saltos.

Os outros agentes (web-agent, IDE, editor) continuam sendo pedidos ao Maestro — ver agents_bridge.py.

Onde cada um está (variáveis de ambiente; várias URLs separadas por vírgula são tentadas em ordem):
  HEALTH_AGENT_URL    padrão http://127.0.0.1:8012  (Pulse, no mesmo Pi)
  FINANCE_AGENT_URL   padrão http://127.0.0.1:8014  (Cifra, no mesmo Pi)
  CAR_AGENT_URL       padrão http://127.0.0.1:8015, depois o PC (Torque — pode estar no Pi ou no PC)
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DOCS_DIR = Path(__file__).resolve().parent.parent / "Docs" / "agents"
_PC = "http://desktop-cc6nlck.local:{port},http://192.168.100.52:{port}"

# name -> como ela chama, onde está e como cada `action` vira uma rota (o mesmo contrato dos adapters do Maestro:
# sem action o pedido vai para o chat do agente; (método, rota, corpo, campo da resposta)).
AGENTS: dict[str, dict[str, Any]] = {
    "health": {
        "title": "Pulse", "spoken": "o Pulse", "env": "HEALTH_AGENT_URL", "default": "http://127.0.0.1:8012",
        "actions": {"overview": ("POST", "/api/overview", None, "text")},
    },
    "finance": {
        "title": "Cifra", "spoken": "a Cifra", "env": "FINANCE_AGENT_URL", "default": "http://127.0.0.1:8014",
        "actions": {"add": ("POST", "/api/transactions/quick", "text", "text"),
                    "summary": ("GET", "/api/summary", None, "text"),
                    "overview": ("POST", "/api/overview", None, "text")},
    },
    "car": {
        "title": "Torque", "spoken": "o Torque", "env": "CAR_AGENT_URL",
        "default": "http://127.0.0.1:8015," + _PC.format(port=8015),
        "actions": {"add": ("POST", "/api/quick", "text", "text"), "status": ("GET", "/api/status", None, "text")},
    },
}
SOURCE = "cassandra"   # como a Cassandra se identifica nos agentes (aparece no histórico deles)
PROBE_TIMEOUT = 2.5
PROBE_TTL = 20.0       # segundos em que a URL que respondeu continua valendo sem conferir de novo
TIMEOUT = float(os.getenv("PERSONAL_AGENT_TIMEOUT", "180"))

_lock = threading.Lock()
_alive: dict[str, tuple[float, str | None]] = {}  # name -> (quando conferiu, URL que respondeu ou None)


def is_personal(name: str) -> bool:
    return name in AGENTS


def urls(name: str) -> list[str]:
    spec = AGENTS[name]
    raw = os.getenv(spec["env"]) or spec["default"]
    return [u.strip().rstrip("/") for u in raw.split(",") if u.strip()]


def _http(method: str, url: str, body: dict | None = None, timeout: float = 15.0) -> tuple[int, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", "User-Agent": "cassandra"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # rede de casa: nunca por proxy
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, (json.loads(raw) if raw else {})
        except ValueError:
            return exc.code, {"detail": raw.decode("utf-8", "replace")[:300]}


def base_url(name: str, fresh: bool = False) -> str | None:
    """A URL em que o agente está respondendo agora (GET /api/health), ou None se está fora do ar."""
    now = time.monotonic()
    with _lock:
        cached = _alive.get(name)
    if cached and not fresh and now - cached[0] < PROBE_TTL:
        return cached[1]
    found = None
    for url in urls(name):
        try:
            status, _ = _http("GET", url + "/api/health", timeout=PROBE_TIMEOUT)
        except (urllib.error.URLError, OSError, ValueError):
            continue
        if status == 200:
            found = url
            break
    with _lock:
        _alive[name] = (time.monotonic(), found)
    return found


def docs(name: str) -> dict[str, str]:
    """A documentação do agente guardada na Cassandra: o que ele faz (capabilities) e a API dele (api)."""
    out = {}
    for key, filename in (("capabilities", "CAPABILITIES.md"), ("api", "API.md")):
        try:
            out[key] = (DOCS_DIR / name / filename).read_text(encoding="utf-8")
        except OSError:
            out[key] = ""
    return out


def tagline(capabilities: str) -> str:
    """A frase de apresentação do CAPABILITIES.md (a primeira citação "> ...")."""
    match = re.search(r"^>\s*(.+)$", capabilities, re.M)
    return match.group(1).strip() if match else ""


def describe(name: str, fresh: bool = False) -> dict[str, Any]:
    """O agente no mesmo formato em que o Maestro descreve os dele — para a Cassandra tratar todos igual."""
    capabilities = docs(name)["capabilities"]
    url = base_url(name, fresh)
    return {"name": name, "title": AGENTS[name]["title"], "tagline": tagline(capabilities),
            "description": capabilities, "status": "online" if url else "offline", "enabled": True,
            "base_url": url or urls(name)[0], "direct": True}


def catalog(fresh: bool = False) -> list[dict[str, Any]]:
    return [describe(name, fresh) for name in AGENTS]


def online() -> list[dict[str, Any]]:
    return [a for a in catalog() if a["status"] == "online"]


def ask(name: str, task: str, parameters: dict | None = None, source: str = SOURCE,
        timeout: float | None = None) -> tuple[bool, str]:
    """Manda o pedido direto ao agente e espera a resposta. -> (deu certo?, resposta ou motivo da falha)"""
    spec = AGENTS.get(name)
    if spec is None:
        return False, f"não conheço o agente pessoal {name!r}"
    url = base_url(name) or base_url(name, fresh=True)
    if not url:
        return False, f"{spec['spoken']} está fora do ar"
    action = str((parameters or {}).get("action") or "").strip().lower()
    method, path, body_key, field = spec["actions"].get(action, ("POST", "/api/chat", "message", "reply"))
    if action == "summary" and (parameters or {}).get("month"):
        path += "?month=" + urllib.request.quote(str(parameters["month"]))
    body = {body_key: task, "source": source} if body_key else ({} if method == "POST" else None)
    try:
        status, data = _http(method, url + path, body, timeout or TIMEOUT)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        with _lock:
            _alive.pop(name, None)  # caiu no meio: a próxima pergunta confere de novo onde ele está
        return False, f"não consegui falar com {spec['spoken']} ({exc})"
    if status != 200:
        detail = (data.get("detail") or data.get("error")) if isinstance(data, dict) else None
        return False, str(detail or f"HTTP {status}")[:300]
    return True, str((data.get(field) if isinstance(data, dict) else "") or "").strip()
