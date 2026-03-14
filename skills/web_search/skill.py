"""Integração com o web-agent: senso crítico + 5 skills especializadas."""
from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from datetime import datetime

import requests
import websockets

from cassandra.openai_client import LLMService
from skills.base import Skill

# ── Configuração ──────────────────────────────────────────────────────────────
WEB_AGENT_URL = os.getenv("WEB_AGENT_URL", "http://192.168.100.52:8000")
WEB_AGENT_EMAIL = os.getenv("WEB_AGENT_EMAIL", "cassandra@assistant.local")
WEB_AGENT_PASSWORD = os.getenv("WEB_AGENT_PASSWORD", "CassandraAgent123!")
_WS_URL = WEB_AGENT_URL.replace("http://", "ws://").replace("https://", "wss://")
_TIMEOUT = int(os.getenv("WEB_AGENT_TIMEOUT", "90"))

# ── Categorias ────────────────────────────────────────────────────────────────
# Cada categoria define: gatilhos para can_handle e prompt de formatação da resposta.

_CATEGORIES: dict[str, dict] = {
    "noticias": {
        "triggers": [
            "notícia", "noticia", "notícias", "noticias",
            "manchete", "manchetes", "o que aconteceu",
            "novidade", "novidades", "atualidade",
            "últimas", "ultimas",
        ],
        "format_prompt": (
            "Você recebeu o resultado de uma busca sobre notícias. "
            "Apresente as manchetes e fatos principais de forma jornalística, "
            "direta e objetiva, em texto corrido. "
            "Priorize os fatos mais relevantes e recentes."
        ),
    },
    "cotacao": {
        "triggers": [
            "cotação", "cotacao", "cotações", "cotacoes",
            "preço de", "preco de", "valor de", "quanto vale", "quanto custa",
            "ação da", "acao da", "ações hoje", "acoes hoje",
            "como estão as ações", "como estao as acoes",
            "como está a bolsa", "como esta a bolsa",
            "bolsa de valores", "bolsa hoje", "bolsa ontem",
            "ibovespa", "b3",
            "nasdaq", "s&p", "dow jones", "nyse",
            "dólar", "dolar", "euro", "libra",
            "bitcoin", "ethereum", "criptomoeda", "cripto",
            "mercado financeiro", "mercado de ações",
            "alta da bolsa", "queda da bolsa",
        ],
        "format_prompt": (
            "Você recebeu dados de cotações financeiras. "
            "Apresente os valores atuais, variações percentuais do dia e uma análise breve. "
            "Use linguagem financeira acessível, em texto corrido, sem jargões excessivos."
        ),
    },
    "clima": {
        "triggers": [
            "previsão do tempo", "previsao do tempo",
            "temperatura em", "temperatura de",
            "vai chover", "vai fazer frio", "vai fazer calor",
            "clima em", "clima de", "como está o tempo",
            "tempo em", "tempo de", "tempo hoje",
            "graus em", "umidade em",
        ],
        "format_prompt": (
            "Você recebeu dados meteorológicos. "
            "Descreva a situação climática atual e a previsão, incluindo temperatura, "
            "probabilidade de chuva e recomendações práticas para o dia. "
            "Seja direto e útil, como uma previsão do tempo de rádio."
        ),
    },
    "esporte": {
        "triggers": [
            "quem ganhou", "resultado do jogo", "resultado de",
            "placar", "placares",
            "classificação", "classificacao", "tabela do",
            "jogou ontem", "joga hoje", "joga amanhã", "joga amanha",
            "campeonato", "copa", "libertadores", "brasileirao", "brasileirão",
            "premier league", "champions", "nfl", "nba", "formula 1", "f1",
            "flamengo", "corinthians", "palmeiras", "são paulo", "sao paulo",
            "cruzeiro", "atletico", "botafogo", "vasco",
        ],
        "format_prompt": (
            "Você recebeu resultados e informações esportivas. "
            "Apresente placares, destaques e curiosidades relevantes "
            "de forma animada mas objetiva, como um locutor esportivo. "
            "Responda em texto corrido."
        ),
    },
    "transito": {
        "triggers": [
            "trânsito", "transito",
            "congestionamento", "engarrafamento",
            "como está a via", "como está a rodovia",
            "estrada", "acidente na", "obra na",
            "como ir para", "melhor caminho para",
        ],
        "format_prompt": (
            "Você recebeu informações de trânsito em tempo real. "
            "Descreva as condições das vias, principais pontos de lentidão e sugestões de rotas alternativas. "
            "Seja prático e direto."
        ),
    },
    "web_geral": {
        "triggers": [
            "pesquise", "pesquisa", "pesquisar",
            "busque", "busca", "buscar",
            "procure", "procura", "procurar",
            "encontre", "encontra",
            "no google", "na internet", "na web",
            "no youtube", "no site",
            "me manda o link", "me passa o link",
            "qual é o presidente", "qual e o presidente",
            "quando é o", "quando e o",
        ],
        "format_prompt": (
            "Você recebeu o resultado de uma pesquisa na internet. "
            "Sintetize as informações mais relevantes de forma clara e objetiva, em texto corrido."
        ),
    },
}

# ── Gatilhos planos (para can_handle rápido) ──────────────────────────────────
_ALL_TRIGGERS: list[str] = []
for _cat in _CATEGORIES.values():
    _ALL_TRIGGERS.extend(_cat["triggers"])

# Padrões de tempo-real não cobertos acima
_REALTIME_EXTRAS = [
    "agora mesmo", "neste momento", "em tempo real",
    "hoje de manhã", "hoje à noite", "hoje a noite",
    "essa semana", "essa manhã", "essa tarde",
    "recém", "acabou de", "acabou de sair",
]
_ALL_TRIGGERS.extend(_REALTIME_EXTRAS)


def _needs_web(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in _ALL_TRIGGERS)


# ── Prompt de classificação (senso crítico) ───────────────────────────────────
_CLASSIFY_SYSTEM = (
    "Você é um classificador de intenção para um assistente pessoal de voz. "
    "Analise a mensagem e responda EXCLUSIVAMENTE com um JSON válido, sem markdown, sem explicação. "
    "Formato obrigatório: "
    '{"category":"<cat>","query":"<consulta>","direct_answer":false} '
    "Categorias válidas: noticias, cotacao, clima, esporte, transito, web_geral. "
    "Use direct_answer:true APENAS se a pergunta pode ser respondida sem internet "
    "(matemática, definição que não muda, piada, conversa, etc.) — neste caso query pode ser vazia. "
    "Para category web_geral: qualquer informação que muda com o tempo ou é factual recente. "
    "O campo query deve ser a consulta OTIMIZADA para o agente web, em português, "
    "incluindo a data de hoje quando relevante. "
    "Seja preciso: prefira 'cotação do dólar hoje 13/03/2026' a 'dólar'."
)


def _classify(llm: LLMService, text: str, today: str) -> dict:
    """Usa gpt-4o-mini para classificar intenção e otimizar a query."""
    raw = llm.client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        max_tokens=120,
        messages=[
            {"role": "system", "content": _CLASSIFY_SYSTEM},
            {"role": "user", "content": f"Data de hoje: {today}\nMensagem: {text}"},
        ],
    ).choices[0].message.content or ""

    # Extrai JSON mesmo se houver texto extra
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    return {"category": "web_geral", "query": text, "direct_answer": False}


# ── Cliente web-agent ─────────────────────────────────────────────────────────

class _WebAgentClient:
    def __init__(self) -> None:
        self._token: str | None = None
        self._token_expires: float = 0.0
        self._session = requests.Session()

    def _base(self, path: str) -> str:
        return f"{WEB_AGENT_URL.rstrip('/')}{path}"

    def _ensure_token(self) -> str | None:
        if self._token and time.time() < self._token_expires:
            return self._token
        try:
            r = self._session.post(
                self._base("/api/auth/login"),
                json={"email": WEB_AGENT_EMAIL, "password": WEB_AGENT_PASSWORD},
                timeout=10,
            )
            if r.status_code == 200:
                self._token = r.json().get("token")
                self._token_expires = time.time() + 23 * 3600
                return self._token
            if r.status_code not in (401, 422):
                return None
        except Exception:
            return None
        try:
            self._session.post(
                self._base("/api/auth/register"),
                json={"email": WEB_AGENT_EMAIL, "password": WEB_AGENT_PASSWORD},
                timeout=10,
            )
            r = self._session.post(
                self._base("/api/auth/login"),
                json={"email": WEB_AGENT_EMAIL, "password": WEB_AGENT_PASSWORD},
                timeout=10,
            )
            if r.status_code == 200:
                self._token = r.json().get("token")
                self._token_expires = time.time() + 23 * 3600
                return self._token
        except Exception:
            pass
        return None

    def _create_chat(self, token: str) -> str | None:
        try:
            r = self._session.post(
                self._base("/api/chats"),
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if r.status_code == 200:
                return r.json().get("id")
        except Exception:
            pass
        return None

    def _get_last_assistant_message(self, token: str, chat_id: str) -> str | None:
        try:
            r = self._session.get(
                self._base(f"/api/chats/{chat_id}"),
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if r.status_code == 200:
                for msg in reversed(r.json().get("display_messages", [])):
                    if msg.get("role") == "assistant":
                        return msg.get("content", "").strip()
        except Exception:
            pass
        return None

    async def _ws_query(self, token: str, chat_id: str, query: str) -> str | None:
        ws_url = f"{_WS_URL}/ws/{chat_id}?token={token}"
        try:
            async with websockets.connect(ws_url, open_timeout=10) as ws:
                await ws.send(json.dumps({"type": "message", "content": query}))

                loop = asyncio.get_running_loop()
                deadline = loop.time() + _TIMEOUT
                seen_agent_activity = False

                while loop.time() < deadline:
                    remaining = deadline - loop.time()
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 5))
                    except asyncio.TimeoutError:
                        continue

                    try:
                        event = json.loads(raw)
                    except Exception:
                        continue

                    etype = event.get("type")

                    if etype == "agent_message":
                        return event.get("content", "").strip()

                    if etype in ("browser_action", "status", "plan", "agent_start"):
                        seen_agent_activity = True

                    if etype == "title_update" and seen_agent_activity:
                        await asyncio.sleep(0.5)
                        return None  # busca via REST abaixo

                    if etype == "error":
                        return None

        except Exception:
            pass
        return None

    def query(self, query: str) -> str | None:
        token = self._ensure_token()
        if not token:
            return None
        chat_id = self._create_chat(token)
        if not chat_id:
            return None

        # Roda o WebSocket em thread dedicada com loop próprio para evitar
        # "This event loop is already running" quando chamado de contexto com loop ativo.
        container: list[str | None] = [None]

        def _run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                container[0] = loop.run_until_complete(
                    self._ws_query(token, chat_id, query)
                )
            finally:
                loop.close()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=_TIMEOUT + 10)

        if container[0] is not None:
            return container[0]
        return self._get_last_assistant_message(token, chat_id)


_client = _WebAgentClient()

# ── Prompts de formatação por categoria ───────────────────────────────────────
_BASE_FORMAT = (
    "Você é a Cassandra, assistente pessoal. "
    "REGRA ABSOLUTA: responda EXCLUSIVAMENTE em português do Brasil. "
    "Sem emojis, sem markdown, sem listas — texto corrido simples, adequado para leitura em voz alta. "
    "Seja direta, objetiva e natural. "
)

_FORMAT_PROMPTS: dict[str, str] = {
    cat: _BASE_FORMAT + data["format_prompt"]
    for cat, data in _CATEGORIES.items()
}
_FORMAT_PROMPTS["direto"] = (
    _BASE_FORMAT
    + "Responda à pergunta do usuário de forma direta e natural, "
    "como em uma conversa. Se não tiver certeza, admita com educação."
)


# ── Skill ─────────────────────────────────────────────────────────────────────

class WebSearchSkill(Skill):
    """
    Skill com senso crítico: usa LLM para detectar quando uma pergunta requer
    informações da web e roteia para o web-agent com uma query otimizada.
    Sub-skills: notícias, cotações, clima, esportes, trânsito, busca geral.
    """

    name = "web_search"

    def __init__(self, llm: LLMService) -> None:
        self.llm = llm

    def can_handle(self, text: str) -> bool:
        """Detecção rápida por palavras-chave como gate de entrada."""
        return _needs_web(text)

    def handle(self, text: str) -> str:
        today = datetime.now().strftime("%d/%m/%Y")

        # ── 1. Senso crítico: classificar intenção e otimizar query ────────────
        intent = _classify(self.llm, text, today)
        category = intent.get("category", "web_geral")
        query = (intent.get("query") or text).strip()
        direct = bool(intent.get("direct_answer", False))

        # ── 2. Se não precisa de web, responde diretamente ─────────────────────
        if direct:
            return self.llm.answer(
                user_text=text,
                system_prompt=_FORMAT_PROMPTS["direto"],
                history=[],
            )

        # ── 3. Consulta o web-agent com a query otimizada ──────────────────────
        raw = _client.query(query)
        if not raw:
            return (
                "Tentei buscar essa informação na internet, mas não obtive resposta "
                "do agente web no momento. Verifique se ele está disponível."
            )

        # ── 4. Formata a resposta com prompt específico da categoria ───────────
        format_prompt = _FORMAT_PROMPTS.get(category, _FORMAT_PROMPTS["web_geral"])
        return self.llm.answer(
            user_text=(
                f"Pergunta original: {text}\n\n"
                f"Resultado da busca na web:\n{raw}"
            ),
            system_prompt=format_prompt,
            history=[],
        )
