"""Integração com o web-agent: senso crítico + 5 skills especializadas."""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime

log = logging.getLogger("web_search")
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
# a checagem do web-agent a cada 15 s geraria uma linha DEBUG do urllib3 por vez no log
logging.getLogger("urllib3").setLevel(logging.WARNING)

import requests

from cassandra.openai_client import LLMService
from skills.base import Skill

# ── Configuração ──────────────────────────────────────────────────────────────
# WEB_AGENT_URL aceita várias URLs separadas por vírgula, tentadas em ordem. O ideal é o nome .local do PC
# onde o web-agent roda (resolvido por mDNS, continua valendo se o roteador trocar o IP) e o IP como reserva:
#   WEB_AGENT_URL=http://desktop-cc6nlck.local:8001,http://192.168.100.52:8001
# O web-agent não tem login (API sem autenticação) e nem sempre está ligado: a Cassandra só o usa quando ele
# responde (checado em segundo plano, ver _WebAgentClient).
WEB_AGENT_URLS = [
    u.strip().rstrip("/")
    for u in os.getenv("WEB_AGENT_URL", "http://192.168.100.52:8001").split(",")
    if u.strip()
]
_TIMEOUT = int(os.getenv("WEB_AGENT_TIMEOUT", "90"))
_PROBE_INTERVAL = 15  # segundos entre checagens de disponibilidade
_PROBE_PATH = "/api/settings/browser"  # leve e só existe no web-agent

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
    raw = llm.create_completion(
        fast=True,
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
    """Cliente do web-agent (API REST, sem login).

    A disponibilidade é checada numa thread em segundo plano a cada _PROBE_INTERVAL s: com o PC desligado,
    cada tentativa leva de 3 a 5 s até desistir (mDNS + conexão), e isso não pode atrasar as respostas.
    Quem usa só lê o último resultado (available()), sem esperar a rede.
    """

    def __init__(self) -> None:
        self._session = requests.Session()
        self._lock = threading.Lock()
        self._base: str | None = None  # URL que respondeu na última checagem; None = indisponível
        self._checked = threading.Event()
        self._monitor: threading.Thread | None = None

    def _probe(self) -> str | None:
        for url in WEB_AGENT_URLS:
            try:
                if requests.get(f"{url}{_PROBE_PATH}", timeout=3).status_code == 200:
                    return url
            except requests.RequestException:
                continue
        return None

    def _refresh(self) -> str | None:
        base = self._probe()
        with self._lock:
            changed = base != self._base
            self._base = base
        self._checked.set()
        if changed:
            print(f"[WEB-AGENT] {'disponível em ' + base if base else 'indisponível'}", flush=True)
        return base

    def _run_monitor(self) -> None:
        while True:
            self._refresh()
            time.sleep(_PROBE_INTERVAL)

    def start(self) -> None:
        with self._lock:
            if self._monitor is None:
                self._monitor = threading.Thread(target=self._run_monitor, name="web-agent-monitor", daemon=True)
                self._monitor.start()

    def available(self) -> str | None:
        """URL do web-agent se ele respondeu na última checagem, senão None. Não bloqueia (só na 1ª vez,
        até a primeira checagem terminar, no máximo alguns segundos)."""
        self.start()
        self._checked.wait(timeout=10)
        with self._lock:
            return self._base

    def status(self) -> dict:
        """Para a tela de Configurações: checa agora (pode levar alguns segundos com o PC desligado)."""
        base = self._refresh()
        return {"connected": bool(base), "url": base or ", ".join(WEB_AGENT_URLS)}

    def query(self, query: str) -> str | None:
        base = self.available()
        if not base:
            return None
        try:
            r = self._session.post(f"{base}/api/chats", timeout=10)
            r.raise_for_status()
            chat_id = r.json().get("id")
            log.debug("Chat criado no web-agent: %s", chat_id)
            # max_seconds: o agente para de navegar e responde com o que coletou antes do nosso timeout
            r = self._session.post(
                f"{base}/api/chats/{chat_id}/message",
                json={"content": query, "max_seconds": max(30, _TIMEOUT - 15)},
                timeout=_TIMEOUT,
            )
            if r.status_code != 200:
                log.error("web-agent respondeu %d: %s", r.status_code, r.text[:200])
                return None
            return (r.json().get("content") or "").strip() or None
        except requests.RequestException as e:
            log.error("Erro falando com o web-agent: %s", e)
            self._refresh()  # talvez tenha sido desligado agora
            return None


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

    # Padrões que indicam conversa pura — não precisam de web, bypass rápido
    _CHAT_ONLY = [
        "obrigado", "valeu", "tchau", "olá", "oi ", "tudo bem",
        "me conta uma piada", "conta uma piada", "piada",
        "me ajuda", "o que você", "quem é você", "você pode",
        "como você", "qual seu nome", "seu nome",
    ]

    def can_handle(self, text: str) -> bool:
        """
        Retorna True para tudo exceto conversa claramente sem web.
        O LLM faz o filtro fino via direct_answer em handle().
        """
        if not _client.available():
            log.debug("can_handle: web-agent indisponível → deixa para as outras skills")
            return False
        t = text.lower()
        # Fast-path: conversa pura → deixa para GeneralChatSkill
        if any(p in t for p in self._CHAT_ONLY) and not _needs_web(t):
            log.debug("can_handle: bypass (conversa pura) | text=%s", text[:60])
            return False
        log.debug("can_handle: True | keyword_match=%s | text=%s", _needs_web(t), text[:60])
        return True

    def handle(self, text: str) -> str:
        today = datetime.now().strftime("%d/%m/%Y")
        log.debug("handle() chamado | text=%s", text[:100])

        # ── 1. Senso crítico: classificar intenção e otimizar query ────────────
        intent = _classify(self.llm, text, today)
        category = intent.get("category", "web_geral")
        query = (intent.get("query") or text).strip()
        direct = bool(intent.get("direct_answer", False))
        log.debug("Classificação: category=%s | direct=%s | query=%s", category, direct, query[:100])

        # ── 2. Se não precisa de web, responde diretamente ─────────────────────
        if direct:
            log.debug("Resposta direta (sem web)")
            return self.llm.answer(
                user_text=text,
                system_prompt=_FORMAT_PROMPTS["direto"],
                history=[],
            )

        # ── 3. Consulta o web-agent com a query otimizada ──────────────────────
        log.debug("Consultando web-agent com query: %s", query)
        raw = _client.query(query)
        log.debug("Resposta do web-agent: %s", repr(raw)[:120] if raw else "NENHUMA")
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
