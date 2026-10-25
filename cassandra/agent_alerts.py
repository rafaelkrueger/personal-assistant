"""Avisos espontâneos dos agentes pessoais (Pulse, Cifra, Torque, Lume).

Os agentes, sozinhos, conferem a situação deles de tempos em tempos e mandam para cá o que merece aviso — "passou do
orçamento de Mercado", "a troca de óleo está vencendo", "você ainda não estudou hoje" — em POST /api/agent-alerts:

  {"agent": "finance", "items": [{"key": "over-Mercado-2026-10", "text": "você passou do orçamento de Mercado…",
                                  "title": "Mercado", "level": "overdue | soon | info", "expires": "ISO (opcional)"}]}

A Cassandra guarda (data/agent_alerts.json, fora do git), e um vigia fala na casa (o aviso entra também no chat):
junta o que chegar em seguida num aviso só, nunca no horário de silêncio (o que chegar fica para depois), nem no meio
de uma conversa ou de um pedido. Aviso que perdeu a validade antes de ser dito (padrão: 18 h) não é falado.

Só aceita pedidos da própria rede (o Pi e a casa) — nunca o que chega pelo túnel público.

Configuração (.env): AGENT_ALERTS_QUIET="22-8" (silêncio das 22h às 8h; "" desliga), AGENT_ALERTS_GATHER=60
(segundos esperando outros avisos para falar junto), AGENT_ALERTS_ENABLED=0 desliga a fala (continua recebendo).
"""
from __future__ import annotations

import ipaddress
import json
import os
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from cassandra import conversation_mode, personal_agents

PATH = Path("data/agent_alerts.json")
KEEP = 300               # avisos guardados (os mais recentes)
DEDUPE_HOURS = 20        # o mesmo aviso (agente + key) que chegar de novo antes disso é ignorado
DEFAULT_TTL_HOURS = 18   # validade de um aviso que ainda não foi dito
MAX_SPOKEN = 6           # num aviso falado; o resto fica no chat
LEVELS = ("overdue", "soon", "info")
_PUBLIC_HEADERS = ("cf-ray", "cf-connecting-ip", "x-forwarded-for", "x-nf-request-id", "x-real-ip")

_lock = threading.Lock()
_thread: threading.Thread | None = None


def _now() -> datetime:
    return datetime.now()


def _read() -> list[dict[str, Any]]:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _write(items: list[dict[str, Any]]) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_name(PATH.name + ".tmp")
    tmp.write_text(json.dumps(items[-KEEP:], ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, PATH)


def from_home(headers: Any, client_ip: str) -> bool:
    """O pedido veio direto da rede de casa (o próprio Pi ou outro aparelho da rede), e não pelo túnel público?
    O túnel entrega como se fosse localhost, mas com os cabeçalhos da Cloudflare/Netlify — esses são recusados."""
    if any(headers.get(h) for h in _PUBLIC_HEADERS):
        return False
    try:
        ip = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


def _text(value: Any, size: int) -> str:
    return " ".join(str(value or "").split())[:size]


def receive(agent: str, items: Any) -> dict[str, Any]:
    """Guarda os avisos que um agente mandou. ValueError se o agente não é um dos pessoais ou não veio nada."""
    if not personal_agents.is_personal(agent):
        raise ValueError(f"agente desconhecido: {agent!r}")
    if not isinstance(items, list) or not items:
        raise ValueError("items deve ser uma lista com pelo menos um aviso")
    now = _now()
    accepted, skipped = [], 0
    with _lock:
        saved = _read()
        recent = {(a["agent"], a["key"]) for a in saved
                  if now - datetime.fromisoformat(a["received_at"]) < timedelta(hours=DEDUPE_HOURS)}
        for raw in items[:20]:
            if not isinstance(raw, dict):
                skipped += 1
                continue
            key, text = _text(raw.get("key"), 120), _text(raw.get("text"), 400)
            if not key or not text or (agent, key) in recent:
                skipped += 1
                continue
            try:
                expires = datetime.fromisoformat(str(raw["expires"])) if raw.get("expires") else None
            except ValueError:
                expires = None
            item = {"id": uuid.uuid4().hex[:10], "agent": agent, "key": key, "title": _text(raw.get("title"), 80),
                    "text": text, "level": raw.get("level") if raw.get("level") in LEVELS else "soon",
                    "received_at": now.isoformat(timespec="seconds"),
                    "expires": (expires or now + timedelta(hours=DEFAULT_TTL_HOURS)).isoformat(timespec="seconds"),
                    "spoken_at": None}
            saved.append(item)
            recent.add((agent, key))
            accepted.append(item)
        if accepted:
            _write(saved)
    return {"ok": True, "accepted": len(accepted), "skipped": skipped}


def recent(limit: int = 50) -> list[dict[str, Any]]:
    with _lock:
        return list(reversed(_read()[-limit:]))


def quiet(now: datetime | None = None, spec: str | None = None) -> bool:
    """Está no horário de silêncio? `spec` "22-8" = das 22h às 8h (atravessa a meia-noite); "" = nunca."""
    spec = os.getenv("AGENT_ALERTS_QUIET", "22-8") if spec is None else spec
    now = now or _now()
    try:
        start, end = (int(x) for x in spec.split("-", 1))
    except ValueError:
        return False
    h = now.hour
    return (start <= h or h < end) if start > end else (start <= h < end)


def _spoken_name(agent: str) -> str:
    return str(personal_agents.AGENTS.get(agent, {}).get("spoken") or agent)


def _sentence(text: str) -> str:
    text = text.strip()
    text = text[:1].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."


def compose(items: list[dict[str, Any]]) -> str:
    """O aviso falado: um por agente, o mais urgente antes ("A Cifra avisa: … O Torque avisa: …")."""
    order = {lv: i for i, lv in enumerate(LEVELS)}
    items = sorted(items, key=lambda a: (order.get(a["level"], 9), a["received_at"]))
    spoken, rest = items[:MAX_SPOKEN], len(items) - MAX_SPOKEN
    by_agent: dict[str, list[str]] = {}
    for a in spoken:
        by_agent.setdefault(a["agent"], []).append(_sentence(a["text"]))
    parts = []
    for agent, texts in by_agent.items():
        name = _spoken_name(agent)
        parts.append(f"{name[:1].upper() + name[1:]} avisa: " + " ".join(texts))
    if rest > 0:
        parts.append(f"E mais {rest} aviso{'s' if rest > 1 else ''} no chat.")
    return " ".join(parts)


def due(now: datetime | None = None, gather: float | None = None) -> list[dict[str, Any]]:
    """Os avisos prontos para falar agora — vazio enquanto ainda pode chegar outro para ir junto. Os vencidos são
    marcados como não ditos (ficam só no registro)."""
    now = now or _now()
    gather = float(os.getenv("AGENT_ALERTS_GATHER", "60")) if gather is None else gather
    with _lock:
        saved = _read()
        changed = False
        pending = []
        for a in saved:
            if a.get("spoken_at"):
                continue
            if datetime.fromisoformat(a["expires"]) < now:
                a["spoken_at"] = "expirou"
                changed = True
                continue
            pending.append(a)
        if changed:
            _write(saved)
    if not pending:
        return []
    newest = max(datetime.fromisoformat(a["received_at"]) for a in pending)
    oldest = min(datetime.fromisoformat(a["received_at"]) for a in pending)
    if (now - newest).total_seconds() < gather and (now - oldest).total_seconds() < gather * 5:
        return []
    return pending


def mark_spoken(ids: list[str], when: str | None = None) -> None:
    when = when or _now().isoformat(timespec="seconds")
    with _lock:
        saved = _read()
        for a in saved:
            if a["id"] in ids:
                a["spoken_at"] = when
        _write(saved)


def _busy(assistant: Any) -> bool:
    """No meio de uma conversa ou de um pedido: o aviso espera."""
    if conversation_mode.active():
        return True
    task = getattr(assistant, "_task_thread", None)
    return bool(task and task.is_alive())


def deliver(assistant: Any, now: datetime | None = None) -> str:
    """Fala o que estiver pronto (se puder agora). -> o texto dito, ou "" se não falou."""
    if os.getenv("AGENT_ALERTS_ENABLED", "1").strip().lower() in {"0", "false", "no", "off"}:
        return ""
    if quiet(now) or _busy(assistant):
        return ""
    items = due(now)
    if not items:
        return ""
    text = compose(items)
    assistant.announce(text)
    mark_spoken([a["id"] for a in items])
    return text


def start(assistant: Any, interval: float = 15.0, log: Callable[[str], None] = print) -> None:
    """O vigia que fala os avisos: confere a cada `interval` segundos."""
    global _thread
    if _thread and _thread.is_alive():
        return

    def loop() -> None:
        while True:
            try:
                said = deliver(assistant)
                if said:
                    log(f"[AVISOS] {said}")
            except Exception as exc:  # noqa: BLE001 — um erro aqui não pode derrubar a Cassandra
                log(f"[AVISOS] erro: {exc}")
            time.sleep(interval)

    _thread = threading.Thread(target=loop, name="agent-alerts", daemon=True)
    _thread.start()
