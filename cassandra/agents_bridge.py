"""Os outros agentes para a Cassandra.

Dois caminhos:
- os AGENTES PESSOAIS (Pulse/health, Cifra/finance, Torque/car): a Cassandra fala DIRETO com eles — ela é a ponte
  deles, sem o Maestro (ver personal_agents.py; a documentação de cada um mora em Docs/agents/);
- os demais (web-agent, IDE, editor…): sempre através do Maestro.

- snapshot(): agentes ligados e no ar agora, com o que cada um faz (o CAPABILITIES.md deles, lido pelo Maestro).
  Nunca bloqueia: devolve o último resultado e atualiza em segundo plano (o Maestro roda no PC, que nem sempre
  está ligado — esperar por ele atrasaria todas as respostas).
- prompt_block(): o texto que entra no prompt do chat, para o LLM da Cassandra saber quem pode fazer o quê.
- catalog() / set_allowed(): a lista de Configurações, com um toggle por agente (quais a Cassandra pode usar).
  Vem do Maestro, então um agente novo aparece sozinho. Os bloqueados ficam em data/agents_access.json.
- run(): manda o pedido com o agente-alvo já escolhido (o Maestro não precisa do LLM dele para decidir) e espera
  um pouco. Se demorar mais, devolve "em andamento" e segue acompanhando em segundo plano; o resultado é falado
  quando chegar (callback on_late_result).
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from cassandra import personal_agents, speech_state
from skills.web_search.skill import _client as _maestro

_REFRESH_EVERY = 60.0  # segundos entre atualizações da lista de agentes
_DESCRIPTION_CHARS = 1800  # tamanho máximo do resumo de cada agente no prompt
_FINAL = {"done", "error", "rejected"}

# Como a Cassandra fala o nome de cada agente em voz alta.
SPOKEN_NAMES = {
    "web-agent": "o web-agent",
    "ide": "o IDE",
    "editor": "o editor de vídeos",
    **{name: spec["spoken"] for name, spec in personal_agents.AGENTS.items()},
}


def spoken(name: str) -> str:
    return SPOKEN_NAMES.get(name, f"o agente {name}")


def _clean(text: str) -> str:
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # [texto](link) -> texto
    return re.sub(r"\s+", " ", re.sub(r"[*`>|#]+", "", text)).strip()


def summarize(agent: dict) -> str:
    """Resumo do CAPABILITIES.md para o prompt: a frase de apresentação + o primeiro trecho de cada item da seção
    "Pode" (ou "O que ele faz"). Cortar o começo do arquivo gastava o espaço com cabeçalhos e explicações para o
    Maestro, e ficavam de fora coisas como o WhatsApp do web-agent."""
    doc = agent.get("description") or ""
    tagline = _clean(agent.get("tagline") or "")
    section = re.search(r"^##\s*(?:Pode|O que ele faz)\b[^\n]*\n(.*?)(?=^##\s|\Z)", doc, re.M | re.S)
    items: list[str] = []
    if section:
        current = ""
        for line in section.group(1).splitlines():
            if re.match(r"\s*[-*]\s+", line):
                if current:
                    items.append(current)
                current = re.sub(r"^\s*[-*]\s+", "", line)
            elif line.strip() and current:
                current += " " + line.strip()
            elif not line.strip() and current:
                items.append(current)
                current = ""
        if current:
            items.append(current)
    # Só o começo de cada item (até o primeiro "—" ou ponto), que é o que diz o que ele faz.
    short = [re.split(r" — |\. |: |; |\(", _clean(i))[0].strip(" .;")[:110] for i in items]
    if tagline and tagline[-1] not in ".!?":
        tagline += "."
    text = tagline + (" Pode: " + "; ".join(s for s in short if s) + "." if short else "")
    return (text or _clean(doc))[:_DESCRIPTION_CHARS]


@dataclass
class AgentReply:
    ok: bool
    text: str = ""
    error: str = ""
    pending: bool = False  # ainda rodando: o resultado vai chegar pelo on_late_result


class AgentsBridge:
    def __init__(self, access_path: str = "data/agents_access.json") -> None:
        self._agents: list[dict] = []
        self._fetched_at = 0.0
        self._refreshing = False
        self._lock = threading.Lock()
        self._access_path = Path(access_path)
        self._blocked: set[str] = self._load_blocked()

    # ── A quais agentes a Cassandra tem acesso (Configurações) ───────────────
    # Guarda só os bloqueados: um agente novo no Maestro aparece na lista e já vem liberado.

    def _load_blocked(self) -> set[str]:
        try:
            data = json.loads(self._access_path.read_text(encoding="utf-8"))
            return {str(n) for n in data.get("blocked", [])}
        except (OSError, ValueError, AttributeError):
            return set()

    def allowed(self, name: str) -> bool:
        with self._lock:
            return name not in self._blocked

    def set_allowed(self, name: str, allowed: bool) -> None:
        with self._lock:
            (self._blocked.discard if allowed else self._blocked.add)(name)
            blocked = sorted(self._blocked)
            self._fetched_at = 0.0  # a próxima conversa já usa a lista nova
        self._access_path.parent.mkdir(parents=True, exist_ok=True)
        self._access_path.write_text(json.dumps({"blocked": blocked}, ensure_ascii=False, indent=2), encoding="utf-8")

    def catalog(self) -> dict:
        """Todos os agentes do Maestro (menos a própria Cassandra), com o acesso de cada um — para a tela de
        Configurações. Busca agora (pode levar alguns segundos com o PC desligado)."""
        link = _maestro._link
        connected = link.available()
        # Os pessoais vêm da própria Cassandra (direto), com ou sem o Maestro; os demais, do Maestro.
        agents = [
            {"name": a["name"], "tagline": a["tagline"], "status": a["status"], "enabled": True,
             "allowed": self.allowed(a["name"]), "direct": True}
            for a in personal_agents.catalog(fresh=True)
        ]
        if connected:
            agents += [
                {"name": a.get("name"), "tagline": a.get("tagline") or "", "status": a.get("status") or "offline",
                 "enabled": a.get("enabled", True), "allowed": self.allowed(a.get("name") or ""), "direct": False}
                for a in link.agents(max_age=5)
                if a.get("name") and a.get("name") != link.agent_name and not personal_agents.is_personal(a["name"])
            ]
        return {"connected": connected, "agents": agents}

    # ── Quem está disponível ─────────────────────────────────────────────────

    def _refresh(self) -> None:
        try:
            agents = _maestro._link.usable_agents() if _maestro._link.available() else []
        except Exception:  # noqa: BLE001 — sem o Maestro, ficam só os agentes pessoais (e tenta de novo depois)
            agents = []
        # Os pessoais não dependem do Maestro: entram os que respondem agora, no lugar da versão que ele listaria.
        agents = [a for a in agents if not personal_agents.is_personal(a.get("name") or "")]
        try:
            agents = personal_agents.online() + agents
        except Exception:  # noqa: BLE001
            pass
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
            blocked = set(self._blocked)
            return [a for a in self._agents if a.get("name") not in blocked]

    def names(self) -> list[str]:
        return [a["name"] for a in self.snapshot() if a.get("name")]

    def prompt_block(self) -> str:
        agents = self.snapshot()
        if not agents:
            return ""
        return "\n".join(f"- {a['name']} ({spoken(a['name'])}): {summarize(a)}" for a in agents)

    # ── Mandar um pedido ─────────────────────────────────────────────────────

    def run(self, target: str, task: str, wait_seconds: float,
            on_late_result: Callable[[str, AgentReply], None] | None = None,
            parameters: dict | None = None) -> AgentReply:
        if personal_agents.is_personal(target):
            return self._run_direct(target, task, wait_seconds, on_late_result, parameters)
        link = _maestro._link
        base = link.base_url or link.refresh()
        if not base:
            return AgentReply(False, error="o Maestro está desligado (o computador pode estar desligado)")
        body = {"from_agent": link.agent_name, "message": task, "target_agent": target}
        if parameters:
            body["parameters"] = parameters
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
        if speech_state.task_cancelled():
            return AgentReply(False, error="interrompido")  # chamaram a Cassandra de novo: nada de resultado depois
        if on_late_result:
            gen = speech_state.task_generation()
            threading.Thread(target=self._follow, args=(link, base, request_id, record, target, on_late_result, gen),
                             daemon=True).start()
        return AgentReply(False, pending=True)

    def _run_direct(self, target: str, task: str, wait_seconds: float,
                    on_late_result: Callable[[str, AgentReply], None] | None, parameters: dict | None) -> AgentReply:
        """Agente pessoal: a Cassandra fala direto com ele. Se passar do tempo de espera, a conversa segue e o
        resultado é falado quando chegar — como nos pedidos feitos pelo Maestro."""
        done = threading.Event()
        box: dict[str, AgentReply] = {}
        late = {"on": False}
        gen = speech_state.task_generation()

        def work() -> None:
            ok, text = personal_agents.ask(target, task, parameters)
            box["reply"] = AgentReply(True, text=text) if ok else AgentReply(False, error=text)
            done.set()
            if late["on"] and on_late_result and not (gen is not None and speech_state.cancelled(gen)):
                try:
                    on_late_result(target, box["reply"])
                except Exception as exc:  # noqa: BLE001
                    print(f"[AGENTES] falha ao avisar o resultado: {exc}", flush=True)

        threading.Thread(target=work, daemon=True).start()
        deadline = time.monotonic() + wait_seconds
        while not done.is_set() and time.monotonic() < deadline and not speech_state.task_cancelled():
            done.wait(0.5)
        if done.is_set():
            return box["reply"]
        if speech_state.task_cancelled():
            return AgentReply(False, error="interrompido")
        late["on"] = True
        if done.is_set():  # terminou bem na virada: devolve agora (o aviso tardio pode repetir, mas nada se perde)
            return box["reply"]
        return AgentReply(False, pending=True)

    @staticmethod
    def _wait(link, base: str, request_id: str, record: dict, seconds: float) -> dict:
        deadline = time.monotonic() + seconds
        while (record.get("status") not in _FINAL and time.monotonic() < deadline
               and not speech_state.task_cancelled()):
            time.sleep(1.0)
            try:
                _, record = link._http(base, "GET", f"{link._prefix}/request/{request_id}", timeout=15)
            except (urllib.error.URLError, OSError):
                continue
        return record

    def _follow(self, link, base, request_id, record, target, callback, gen=None) -> None:
        record = self._wait(link, base, request_id, record, 30 * 60)  # tarefas longas (ex.: IDE): até 30 min
        if gen is not None and speech_state.cancelled(gen):
            return  # a pessoa interrompeu a Cassandra depois desse pedido: não fala o resultado velho
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
