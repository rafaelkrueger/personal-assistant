"""Os agentes pessoais — Pulse (saúde), Cifra (finanças), Torque (carro) — falados DIRETO pela Cassandra.

A regra do sistema é que nenhum agente chama outro: a ponte é o Maestro. A Cassandra é a exceção, e só para os
agentes pessoais: ela é a "maestra" deles. Guarda aqui a documentação de cada um (Docs/agents/<nome>/, cópia do
CAPABILITIES.md e do API.md do agente — sincronizada por orchestrator/plugin/sync_copies.py) e fala com eles por
HTTP, sem passar pelo Maestro. Assim os agentes pessoais continuam funcionando com o computador desligado (os que
moram no Raspberry Pi) e a conversa não depende de dois saltos.

Os outros agentes (web-agent, IDE, editor) continuam sendo pedidos ao Maestro — ver agents_bridge.py.

Além de conversar, a Cassandra mostra na interface dela o principal de cada um ("destaques": o que pede atenção e
os números do momento), lido das rotas de leitura do próprio agente — ver overview().

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
READ_TIMEOUT = 6.0     # leitura dos destaques: curta, para um agente lento não segurar a tela da Cassandra
OVERVIEW_TTL = 30.0    # segundos em que os destaques já lidos servem de novo (o painel pede a cada atualização)
TIMEOUT = float(os.getenv("PERSONAL_AGENT_TIMEOUT", "180"))

_lock = threading.Lock()
_alive: dict[str, tuple[float, str | None]] = {}  # name -> (quando conferiu, URL que respondeu ou None)
_overview: tuple[float, list[dict[str, Any]]] | None = None  # (quando leu, os destaques de todos)


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
    global _overview
    with _lock:
        _overview = None  # a conversa pode ter mudado os números do agente: os destaques são lidos de novo
    return True, str((data.get(field) if isinstance(data, dict) else "") or "").strip()


# ── destaques: o principal de cada agente, para a tela da Cassandra ───────────

def _brl(value: Any) -> str:
    try:
        text = f"{float(value or 0):,.2f}"
    except (TypeError, ValueError):
        return "—"
    return "R$ " + text.replace(",", "X").replace(".", ",").replace("X", ".")


def _day(iso: Any) -> str:
    text = str(iso or "")
    return f"{text[8:10]}/{text[5:7]}/{text[:4]}" if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", text) else text


def _get(url: str, path: str) -> dict[str, Any]:
    status, data = _http("GET", url + path, timeout=READ_TIMEOUT)
    return data if status == 200 and isinstance(data, dict) else {}


def _item(label: str, value: Any, tone: str = "") -> dict[str, str]:
    """Um número do agente. tone: "" (neutro), "ok", "warn" ou "bad" — a cor com que a Cassandra mostra."""
    return {"label": label, "value": str(value), "tone": tone}


def _health_highlights(url: str) -> tuple[list[dict], list[dict]]:
    checkup, weight = _get(url, "/api/checkup"), _get(url, "/api/weight")
    items, alerts = [], []
    if checkup:
        counts, tips = checkup.get("counts") or {}, (checkup.get("suggestions") or {}).get("items") or []
        todo = len(tips) + (counts.get("overdue") or 0) + (counts.get("soon") or 0)
        progress = checkup.get("progress") or {}
        items.append(_item("Para fazer agora", todo, "warn" if todo else "ok"))
        items.append(_item("Checkup em dia", f"{progress.get('done', 0)} de {progress.get('total', 0)}"))
        alerts += [{"text": tip.get("name") or "", "tone": "warn"} for tip in tips[:2]]
        alerts += [{"text": i["name"] + " (atrasado)", "tone": "bad"}
                   for i in checkup.get("items") or [] if i.get("status") == "overdue"][:2]
        upcoming = checkup.get("next")
        if upcoming:
            items.append(_item("Próximo exame", f"{upcoming.get('name')} · {_day(upcoming.get('due_date'))}"))
    if weight.get("ready"):
        today, streak = weight.get("today") or {}, weight.get("streak") or {}
        items.append(_item("Calorias hoje", f"{today.get('kcal', 0)} de {weight.get('calories')} kcal",
                           "ok" if today.get("hit") else ""))
        if streak.get("current"):
            items.append(_item("Sequência", f"{streak['current']} dia(s)", "ok"))
    return items, alerts


def _finance_highlights(url: str) -> tuple[list[dict], list[dict]]:
    summary, debts = _get(url, "/api/summary"), (_get(url, "/api/debts").get("summary") or {})
    items, alerts = [], []
    if summary:
        balance = summary.get("balance") or 0
        items.append(_item(f"Saldo de {summary.get('label') or 'este mês'}", _brl(balance), "bad" if balance < 0 else "ok"))
        items.append(_item("Entrou", _brl(summary.get("income"))))
        items.append(_item("Saiu", _brl(summary.get("expenses"))))
        if balance < 0:
            alerts.append({"text": "O mês está no vermelho", "tone": "bad"})
    if debts.get("count"):
        items.append(_item("Dívidas", _brl(debts.get("total")), "warn"))
        if debts.get("monthly"):
            items.append(_item("Parcelas por mês", _brl(debts.get("monthly"))))
    return items, alerts


def _car_highlights(url: str) -> tuple[list[dict], list[dict]]:
    status = _get(url, "/api/status")
    items, alerts = [], []
    if status:
        miles, counts = status.get("mileage") or {}, status.get("plan_counts") or {}
        urgent = [a for a in status.get("alerts") or [] if a.get("level") in ("overdue", "soon")]
        late = any(a.get("level") == "overdue" for a in urgent)
        if miles.get("km") is not None:
            items.append(_item("Hodômetro", f"{int(miles.get('estimated_km') or miles['km']):,} km".replace(",", ".")))
        items.append(_item("Pede atenção", len(urgent), "bad" if late else "warn" if urgent else "ok"))
        items.append(_item("Manutenção em dia", f"{counts.get('ok', 0)} de {sum(counts.values()) if counts else 0}"))
        month = ((status.get("costs") or {}).get("this_month") or {}).get("total")
        if month:
            items.append(_item("Gasto neste mês", _brl(month)))
        alerts += [{"text": a.get("title") or "", "tone": "bad" if a.get("level") == "overdue" else "warn"} for a in urgent[:3]]
    return items, alerts


_HIGHLIGHTS = {"health": _health_highlights, "finance": _finance_highlights, "car": _car_highlights}


def highlights(name: str) -> dict[str, Any]:
    """O agente como a tela da Cassandra o mostra: se está no ar, onde abrir, os números do momento e o que pede
    atenção. Nunca levanta: agente fora do ar ou resposta estranha vira lista vazia."""
    capabilities = docs(name)["capabilities"]
    url = base_url(name)
    out = {"name": name, "title": AGENTS[name]["title"], "tagline": tagline(capabilities),
           "status": "online" if url else "offline", "base_url": url or urls(name)[0], "highlights": [], "alerts": []}
    if url:
        try:
            items, alerts = _HIGHLIGHTS[name](url)
            out["highlights"], out["alerts"] = items, [a for a in alerts if a.get("text")]
        except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as exc:
            out["error"] = str(exc)[:200]
    return out


def overview(fresh: bool = False) -> list[dict[str, Any]]:
    """Os destaques de todos os agentes pessoais, lidos em paralelo (e guardados por OVERVIEW_TTL)."""
    global _overview
    with _lock:
        cached = _overview
    if cached and not fresh and time.monotonic() - cached[0] < OVERVIEW_TTL:
        return cached[1]
    results: dict[str, dict[str, Any]] = {}
    threads = [threading.Thread(target=lambda n=name: results.__setitem__(n, highlights(n)), daemon=True) for name in AGENTS]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(READ_TIMEOUT * 3)
    data = [results.get(name) or {"name": name, "title": AGENTS[name]["title"], "tagline": "", "status": "offline",
                                  "base_url": urls(name)[0], "highlights": [], "alerts": []} for name in AGENTS]
    with _lock:
        _overview = (time.monotonic(), data)
    return data


def history(name: str, limit: int = 40) -> list[dict[str, str]]:
    """As últimas mensagens da conversa do próprio agente (a mesma que aparece na tela dele)."""
    url = base_url(name)
    if not url:
        return []
    try:
        messages = _get(url, "/api/chat").get("messages") or []
    except (urllib.error.URLError, OSError, ValueError):
        return []
    return [{"role": "assistant" if m.get("role") == "assistant" else "user", "content": str(m.get("content") or "")}
            for m in messages[-limit:] if isinstance(m, dict) and str(m.get("content") or "").strip()]
