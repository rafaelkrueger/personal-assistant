"""Busca na internet via maestro (que despacha para o web-agent): senso crítico + 5 skills especializadas."""
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

from cassandra.maestro_link import MaestroLink, _env

from cassandra.openai_client import LLMService
from skills.base import Skill

# ── Configuração ──────────────────────────────────────────────────────────────
# A Cassandra não fala com outros agentes direto: pede ao MAESTRO (a ponte entre os agentes), que
# escolhe quem executa — pesquisas na internet vão para o web-agent. Plug-in: cassandra/maestro_link.py
# (cópia de maestro/plugin/maestro_link.py). Configuração no .env:
#   MAESTRO_URL=http://desktop-cc6nlck.local:8090,http://192.168.100.52:8090   (tentadas em ordem)
#   MAESTRO_TOKEN=<MAESTRO_SHARED_SECRET do maestro>
# O maestro roda no PC e nem sempre está ligado: a Cassandra só o usa quando ele responde (checado em
# segundo plano pelo plug-in).
# (os nomes antigos ORCHESTRATOR_* continuam valendo: _env cai neles se MAESTRO_* não existir)
_TIMEOUT = int(_env("MAESTRO_TIMEOUT", "120"))
# Quando o maestro responde mas o pedido falha (ex.: o LLM do web-agent fora do ar), fica de lado por
# um tempo — senão cada pergunta perde dezenas de segundos esperando falhar de novo.
_FAILURE_COOLDOWN = 300

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


# ── Cliente do maestro ───────────────────────────────────────────────────

class _MaestroClient:
    """Pedidos a outros agentes, sempre através do maestro (plug-in maestro_link).

    A disponibilidade é checada em segundo plano pelo plug-in: com o PC desligado, cada tentativa leva alguns
    segundos até desistir, e isso não pode atrasar as respostas. Quem usa só lê o último resultado.
    """

    def __init__(self) -> None:
        self._link = MaestroLink.from_env(
            agent_name=_env("MAESTRO_AGENT_NAME", "personal-assistant"),
            request_timeout=_TIMEOUT,
        )
        self._failed_until = 0.0

    def start(self) -> None:
        self._link.start()

    def available(self) -> bool:
        if time.monotonic() < self._failed_until:
            return False
        return self._link.available()

    def status(self) -> dict:
        """Para a tela de Configurações: checa agora (pode levar alguns segundos com o PC desligado)."""
        return self._link.status()

    def _mark_failed(self, reason: str) -> None:
        self._failed_until = time.monotonic() + _FAILURE_COOLDOWN
        print(f"[MAESTRO] pedido falhou ({reason[:150]}); sem usar por {_FAILURE_COOLDOWN // 60} min", flush=True)

    def query(self, query: str) -> str | None:
        """Pesquisa na internet via maestro (que despacha para o web-agent). None se não houver resposta."""
        if not self.available():
            return None
        result = self._link.ask(
            f"Pesquise na internet e responda em português, de forma objetiva: {query}",
            # orçamento de tempo do web-agent: ele para de navegar e responde com o que coletou antes do nosso prazo
            parameters={"max_seconds": max(30, _TIMEOUT - 20)},
            timeout=_TIMEOUT,
        )
        if not result.ok:
            self._mark_failed(result.error or result.status or "sem resposta")
            return None
        log.debug("maestro despachou para %s", result.target_agent)
        return (result.result or "").strip() or None


_client = _MaestroClient()

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
    informações da web e pede ao maestro (que usa o web-agent) com uma query otimizada.
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
            log.debug("can_handle: maestro indisponível → deixa para as outras skills")
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

        # ── 3. Pede a pesquisa ao maestro (que despacha para o web-agent) ──
        log.debug("Pedindo ao maestro: %s", query)
        raw = _client.query(query)
        log.debug("Resposta via maestro: %s", repr(raw)[:120] if raw else "NENHUMA")
        if not raw:
            # o maestro (ou o agente que ele escolheu) falhou: responde com o próprio LLM
            log.debug("maestro sem resposta → respondendo direto com o LLM")
            return self.llm.answer(
                user_text=text,
                system_prompt=_FORMAT_PROMPTS["direto"],
                history=[],
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
