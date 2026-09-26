"""Maestro Link — o plug-in para um agente falar com o maestro.

O maestro é a ponte entre todos os agentes: um agente nunca chama outro direto. Quando precisa de algo
que outro agente faz (pesquisar na web, transcrever um vídeo, escrever código, avisar alguém em casa…), ele
pede ao maestro, que escolhe quem executa (ou usa o alvo indicado), despacha e devolve o resultado.

Este arquivo é autocontido (só biblioteca padrão, Python 3.9+): cada agente em Python leva uma cópia dele.
A cópia canônica fica em maestro/plugin/maestro_link.py — ao mudar aqui, copie para os agentes
(o VERSION ajuda a conferir). Agentes que não são Python usam a linha de comando (ver no fim).

Configuração (variáveis de ambiente, ou argumentos do construtor):
  MAESTRO_URL         uma ou mais URLs base, separadas por vírgula, tentadas em ordem
                           (ex.: http://desktop-cc6nlck.local:8090,http://192.168.100.52:8090)
  MAESTRO_TOKEN       o MAESTRO_SHARED_SECRET do maestro (obrigatório para pedir tarefas;
                           listar agentes e checar saúde não precisam)
  MAESTRO_AGENT_NAME  o nome deste agente no maestro (vai como from_agent)
  MAESTRO_WEB_USER    o usuário DESTE agente no web-agent (os logins/cookies/WhatsApp dele lá): vai em todo
                           pedido como web_user. Padrão: o próprio MAESTRO_AGENT_NAME. Cada agente tem o seu.
Os nomes antigos (ORCHESTRATOR_URL, ORCHESTRATOR_TOKEN, ORCHESTRATOR_SHARED_SECRET, ORCHESTRATOR_AGENT_NAME — de antes
do rename orchestrator -> maestro) continuam valendo, e o plug-in fala com um maestro antigo (rotas /orchestrator/*).

Uso:
    from maestro_link import MaestroLink

    link = MaestroLink.from_env()
    if link.available():                       # não bloqueia: checagem em segundo plano
        r = link.ask("pesquise a cotação do dólar hoje")          # o maestro escolhe o agente
        r = link.ask("transcreva https://youtu.be/…", target="editor")  # ou indique quem executa
        if r.ok:
            print(r.result)
    for a in link.agents():                    # tudo que o maestro controla
        print(a["name"], a["enabled"], a["status"], a["tagline"])

Linha de comando:
    python maestro_link.py status
    python maestro_link.py agents
    python maestro_link.py ask "mensagem" [--target web-agent] [--from ide] [--web-user ide] [--timeout 600] [--json]
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any

VERSION = "1.2"

_FINAL_STATUSES = {"done", "error", "rejected"}


@dataclass
class LinkResult:
    ok: bool
    result: str | None = None
    error: str | None = None
    status: str | None = None
    target_agent: str | None = None
    request_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


def _env(name: str, default: str = "") -> str:
    """MAESTRO_<X> e, por compatibilidade, o nome antigo ORCHESTRATOR_<X>."""
    value = os.getenv(name)
    if value is None and name.startswith("MAESTRO_"):
        value = os.getenv("ORCHESTRATOR_" + name[len("MAESTRO_"):])
    return default if value is None else value


class MaestroLink:
    def __init__(
        self,
        urls: list[str] | str | None,
        token: str = "",
        agent_name: str = "",
        web_user: str = "",
        probe_interval: float = 15.0,
        request_timeout: float = 300.0,
        poll_interval: float = 1.5,
    ) -> None:
        if isinstance(urls, str):
            urls = urls.split(",")
        self.urls = [u.strip().rstrip("/") for u in (urls or []) if u and u.strip()]
        self.token = (token or "").strip()
        self.agent_name = (agent_name or "").strip()
        # usuário deste agente no web-agent (cada agente com os próprios logins lá); padrão: o nome do agente
        self.web_user = (web_user or self.agent_name).strip().lower()
        self.probe_interval = probe_interval
        self.request_timeout = request_timeout
        self.poll_interval = poll_interval
        self._lock = threading.Lock()
        self._base: str | None = None
        self._checked = threading.Event()
        self._monitor: threading.Thread | None = None
        self._agents_cache: tuple[float, list[dict]] | None = None
        # prefixo das rotas: /maestro, ou /orchestrator num servidor de antes do rename (descoberto no probe)
        self._prefix = "/maestro"

    @classmethod
    def from_env(cls, agent_name: str | None = None, **kwargs: Any) -> "MaestroLink":
        return cls(
            _env("MAESTRO_URL", "http://127.0.0.1:8090"),
            token=_env("MAESTRO_TOKEN") or _env("MAESTRO_SHARED_SECRET"),
            agent_name=agent_name or _env("MAESTRO_AGENT_NAME"),
            web_user=kwargs.pop("web_user", None) or _env("MAESTRO_WEB_USER"),
            **kwargs,
        )

    # ── HTTP ──────────────────────────────────────────────────────────────────

    def _http(self, base: str, method: str, path: str, body: dict | None = None, timeout: float = 15.0):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json", "User-Agent": f"maestro-link/{VERSION}"}
        if self.token:
            headers["X-Maestro-Token"] = self.token
            headers["X-Orchestrator-Token"] = self.token  # servidores de antes do rename
        req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                payload = json.loads(raw) if raw else {}
            except ValueError:
                payload = {"detail": raw.decode("utf-8", "replace")[:300]}
            return exc.code, payload

    # ── Disponibilidade (checada em segundo plano) ────────────────────────────

    def _probe(self) -> str | None:
        for base in self.urls:
            for prefix in ("/maestro", "/orchestrator"):
                try:
                    status, _ = self._http(base, "GET", f"{prefix}/health", timeout=3)
                except (urllib.error.URLError, OSError, ValueError):
                    break  # nem conecta: tenta a próxima URL
                if status == 200:
                    self._prefix = prefix
                    return base
                if status != 404:
                    break
        return None

    def refresh(self) -> str | None:
        """Checa agora qual URL responde (bloqueia alguns segundos se o maestro estiver fora)."""
        base = self._probe()
        with self._lock:
            changed = base != self._base
            self._base = base
        self._checked.set()
        if changed:
            # stderr: na linha de comando o stdout é só o resultado (ex.: JSON de `status`)
            print(f"[MAESTRO] {'disponível em ' + base if base else 'indisponível'}", file=sys.stderr, flush=True)
        return base

    def _run_monitor(self) -> None:
        while True:
            self.refresh()
            time.sleep(self.probe_interval)

    def start(self) -> None:
        """Liga a checagem periódica em segundo plano (idempotente)."""
        with self._lock:
            if self._monitor is None and self.urls:
                self._monitor = threading.Thread(target=self._run_monitor, name="maestro-link", daemon=True)
                self._monitor.start()

    def available(self) -> bool:
        """True se o maestro respondeu na última checagem. Não bloqueia (só na 1ª vez, até ~10 s)."""
        self.start()
        self._checked.wait(timeout=10)
        with self._lock:
            return self._base is not None

    @property
    def base_url(self) -> str | None:
        with self._lock:
            return self._base

    def status(self) -> dict[str, Any]:
        base = self.refresh()
        return {
            "connected": bool(base),
            "url": base or ", ".join(self.urls),
            "agent_name": self.agent_name,
            "web_user": self.web_user,
            "token_set": bool(self.token),
            "version": VERSION,
        }

    # ── O que o maestro controla ─────────────────────────────────────────

    def agents(self, max_age: float = 30.0) -> list[dict[str, Any]]:
        """Agentes do maestro: name, tagline, description (o CAPABILITIES.md inteiro), status
        (online/offline/cli), enabled (toggle), managed, base_url. Cacheado por max_age segundos."""
        cached = self._agents_cache
        if cached and time.monotonic() - cached[0] < max_age:
            return cached[1]
        base = self.base_url or self.refresh()
        if not base:
            return []
        status, payload = self._http(base, "GET", f"{self._prefix}/agents", timeout=10)
        agents = payload.get("agents", []) if status == 200 else []
        self._agents_cache = (time.monotonic(), agents)
        return agents

    def usable_agents(self) -> list[dict[str, Any]]:
        """Agentes que podem receber um pedido deste agente agora: ligados, no ar (ou CLI) e não ele mesmo."""
        return [
            a for a in self.agents()
            if a.get("name") != self.agent_name and a.get("enabled", True) and a.get("status") in ("online", "cli", "degraded")
        ]

    # ── Pedir uma tarefa ──────────────────────────────────────────────────────

    def ask(
        self,
        message: str,
        target: str | None = None,
        parameters: dict[str, Any] | None = None,
        timeout: float | None = None,
        web_user: str | None = None,
    ) -> LinkResult:
        """Pede ao maestro que um agente execute `message` e espera o resultado.
        Sem `target`, o maestro escolhe o agente pelo pedido. `web_user` (padrão: o deste agente) é o usuário
        no web-agent cujos logins/cookies são usados, se o pedido for parar lá."""
        if not self.agent_name:
            return LinkResult(ok=False, error="MAESTRO_AGENT_NAME não configurado (quem está pedindo?).")
        if not self.token:
            return LinkResult(ok=False, error="MAESTRO_TOKEN não configurado.")
        base = self.base_url or self.refresh()
        if not base:
            return LinkResult(ok=False, error=f"Maestro indisponível ({', '.join(self.urls)}).")
        body: dict[str, Any] = {"from_agent": self.agent_name, "message": message}
        if target:
            body["target_agent"] = target
        if parameters:
            body["parameters"] = parameters
        if web_user or self.web_user:
            body["web_user"] = (web_user or self.web_user).strip().lower()
        try:
            status, created = self._http(base, "POST", f"{self._prefix}/request", body, timeout=15)
        except (urllib.error.URLError, OSError) as exc:
            self.refresh()
            return LinkResult(ok=False, error=f"Não consegui falar com o maestro: {exc}")
        if status != 200:
            return LinkResult(ok=False, status=str(status), error=str(created.get("detail") or created))
        request_id = created.get("request_id")
        deadline = time.monotonic() + (timeout if timeout is not None else self.request_timeout)
        record = created
        while record.get("status") not in _FINAL_STATUSES:
            if time.monotonic() >= deadline:
                return LinkResult(
                    ok=False, status=record.get("status"), request_id=request_id, target_agent=record.get("target_agent"),
                    error="Tempo esgotado esperando o resultado (o pedido continua rodando no maestro).",
                )
            time.sleep(self.poll_interval)
            try:
                _, record = self._http(base, "GET", f"{self._prefix}/request/{request_id}", timeout=15)
            except (urllib.error.URLError, OSError):
                continue  # oscilação de rede: tenta de novo até o prazo
        return LinkResult(
            ok=record.get("status") == "done",
            result=record.get("result"),
            error=record.get("error"),
            status=record.get("status"),
            target_agent=record.get("target_agent"),
            request_id=request_id,
            details={"task_summary": record.get("task_summary")},
        )


# Nome antigo da classe (antes do rename orchestrator -> maestro).
OrchestratorLink = MaestroLink


# ── Linha de comando ──────────────────────────────────────────────────────────────────────────────


def _main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="maestro_link", description="Fala com o maestro (a ponte entre os agentes).")
    parser.add_argument("--url", help="URL(s) do maestro (padrão: MAESTRO_URL)")
    parser.add_argument("--token", help="token (padrão: MAESTRO_TOKEN / MAESTRO_SHARED_SECRET)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="o maestro está no ar?")
    sub.add_parser("agents", help="agentes que ele controla")
    ask = sub.add_parser("ask", help="pede uma tarefa e espera o resultado")
    ask.add_argument("message")
    ask.add_argument("--target", help="agente que deve executar (sem isso, o maestro escolhe)")
    ask.add_argument("--from", dest="from_agent", help="nome deste agente (padrão: MAESTRO_AGENT_NAME)")
    ask.add_argument("--web-user", dest="web_user",
                     help="usuário deste agente no web-agent (padrão: MAESTRO_WEB_USER, ou o nome do agente)")
    ask.add_argument("--timeout", type=float, default=600.0)
    ask.add_argument("--json", action="store_true", help="imprime o resultado completo em JSON")
    args = parser.parse_args(argv)

    link = MaestroLink.from_env(agent_name=getattr(args, "from_agent", None), web_user=getattr(args, "web_user", None))
    if args.url:
        link.urls = [u.strip().rstrip("/") for u in args.url.split(",") if u.strip()]
    if args.token:
        link.token = args.token

    if args.cmd == "status":
        print(json.dumps(link.status(), ensure_ascii=False, indent=2))
        return 0 if link.base_url else 1
    if args.cmd == "agents":
        link.refresh()
        for a in link.agents():
            state = "ligado" if a.get("enabled", True) else "DESLIGADO"
            print(f"{a['name']:20} {a.get('status', '?'):9} {state:9} {a.get('tagline', '')}")
        return 0
    result = link.ask(args.message, target=args.target, timeout=args.timeout)
    if args.json:
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    elif result.ok:
        print(result.result or "")
    else:
        print(f"ERRO: {result.error}", file=sys.stderr)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
