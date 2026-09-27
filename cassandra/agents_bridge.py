"""Os outros agentes (web-agent, IDE, editor, Health...) para a Cassandra, sempre através do Maestro.

- snapshot(): agentes ligados e no ar agora, com o que cada um faz (o CAPABILITIES.md deles, lido pelo Maestro).
  Nunca bloqueia: devolve o último resultado e atualiza em segundo plano (o Maestro roda no PC, que nem sempre
  está ligado — esperar por ele atrasaria todas as respostas).
- prompt_block(): o texto que entra no prompt do chat, para o LLM da Cassandra saber quem pode fazer o quê.
- run(): manda o pedido com o agente-alvo já escolhido (o Maestro não precisa do LLM dele para decidir) e espera
  um pouco. Se demorar mais, devolve "em andamento" e segue acompanhando em segundo plano; o resultado é falado
  quando chegar (callback on_late_result).
"""
from __future__ import annotations

import re
import threading
import time
import urllib.error
from dataclasses import dataclass
from typing import Callable

from skills.web_search.skill import _client as _maestro

_REFRESH_EVERY = 60.0  # segundos entre atualizações da lista de agentes
_DESCRIPTION_CHARS = 900  # quanto do CAPABILITIES.md de cada agente vai para o prompt
_FINAL = {"done", "error", "rejected"}

# Como a Cassandra fala o nome de cada agente em voz alta.
SPOKEN_NAMES = {
    "web-agent": "o web-agent",
    "ide": "o IDE",
    "editor": "o editor de vídeos",
    "health": "o Health",
}


def spoken(name: str) -> str:
    return SPOKEN_NAMES.get(name, f"o agente {name}")


@dataclass
class AgentReply:
    ok: bool
    text: str = ""
    error: str = ""
    pending: bool = False  # ainda rodando: o resultado vai chegar pelo on_late_result


class AgentsBridge:
    def __init__(self) -> None:
        self._agents: list[dict] = []
        self._fetched_at = 0.0
        self._refreshing = False
        self._lock = threading.Lock()

    # ── Quem está disponível ─────────────────────────────────────────────────

    def _refresh(self) -> None:
        try:
            agents = _maestro._link.usable_agents() if _maestro._link.available() else []
        except Exception:  # noqa: BLE001 — sem o Maestro, fica sem agentes (e tenta de novo depois)
            agents = []
        with self._lock:
            self._agents = agents
            self._fetched_at = time.monotonic()
            self._refreshing = False

    def snapshot(self) -> list[dict]:
        with self._lock:
            stale = time.monotonic() - self._fetched_at > _REFRESH_EVERY
            if stale and not self._refreshing:
                self._refreshing = True
                threading.Thread(target=self._refresh, daemon=True).start()
            return list(self._agents)

    def names(self) -> list[str]:
        return [a["name"] for a in self.snapshot() if a.get("name")]

    def prompt_block(self) -> str:
        agents = self.snapshot()
        if not agents:
            return ""
        parts = []
        for a in agents:
            desc = re.sub(r"[#>*`|]+", " ", a.get("description") or a.get("tagline") or "")
            desc = re.sub(r"\s+", " ", desc).strip()[:_DESCRIPTION_CHARS]
            parts.append(f"- {a['name']} ({spoken(a['name'])}): {desc}")
        return "\n".join(parts)

    # ── Mandar um pedido ─────────────────────────────────────────────────────

    def run(self, target: str, task: str, wait_seconds: float,
            on_late_result: Callable[[str, AgentReply], None] | None = None) -> AgentReply:
        link = _maestro._link
        base = link.base_url or link.refresh()
        if not base:
            return AgentReply(False, error="o Maestro está desligado (o computador pode estar desligado)")
        body = {"from_agent": link.agent_name, "message": task, "target_agent": target}
        if link.web_user:
            body["web_user"] = link.web_user
        try:
            status, created = link._http(base, "POST", f"{link._prefix}/request", body, timeout=15)
        except (urllib.error.URLError, OSError) as exc:
            return AgentReply(False, error=f"não consegui falar com o Maestro ({exc})")
        if status != 200:
            return AgentReply(False, error=str(created.get("detail") or created)[:300])
        request_id = created.get("request_id")
        record = self._wait(link, base, request_id, created, wait_seconds)
        if record.get("status") in _FINAL:
            return self._reply(record)
        if on_late_result:
            threading.Thread(target=self._follow, args=(link, base, request_id, record, target, on_late_result),
                             daemon=True).start()
        return AgentReply(False, pending=True)

    @staticmethod
    def _wait(link, base: str, request_id: str, record: dict, seconds: float) -> dict:
        deadline = time.monotonic() + seconds
        while record.get("status") not in _FINAL and time.monotonic() < deadline:
            time.sleep(1.0)
            try:
                _, record = link._http(base, "GET", f"{link._prefix}/request/{request_id}", timeout=15)
            except (urllib.error.URLError, OSError):
                continue
        return record

    def _follow(self, link, base, request_id, record, target, callback) -> None:
        record = self._wait(link, base, request_id, record, 30 * 60)  # tarefas longas (ex.: IDE): até 30 min
        reply = self._reply(record) if record.get("status") in _FINAL else AgentReply(
            False, error="passou de 30 minutos sem terminar")
        try:
            callback(target, reply)
        except Exception as exc:  # noqa: BLE001
            print(f"[AGENTES] falha ao avisar o resultado: {exc}", flush=True)

    @staticmethod
    def _reply(record: dict) -> AgentReply:
        if record.get("status") == "done":
            return AgentReply(True, text=(record.get("result") or "").strip())
        return AgentReply(False, error=(record.get("error") or record.get("status") or "falhou")[:300])


bridge = AgentsBridge()
