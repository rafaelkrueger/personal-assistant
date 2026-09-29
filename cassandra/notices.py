"""Avisos curtos falados antes de algo que demora (pesquisa na internet, pedido a outro agente), para a pessoa não
ficar no silêncio sem saber se a Cassandra ouviu. Sorteados para não soar repetitivo."""
from __future__ import annotations

import random

_SEARCH = (
    "Deixa eu dar uma olhada nisso.",
    "Um instante, estou buscando.",
    "Só um momento que eu confiro.",
    "Já estou procurando, aguenta um pouquinho.",
    "Certo, vou pesquisar. Um segundo.",
    "Boa pergunta, deixa eu checar.",
    "Pode deixar, estou vendo isso agora.",
)

_TASK = (
    "Pode deixar, já estou cuidando disso.",
    "Certo, vou resolver isso. Um instante.",
    "Beleza, estou providenciando.",
    "Deixa comigo, só um momento.",
    "Já estou nisso, aguenta um pouquinho.",
)

_last: dict[str, str] = {}


class Notice(str):
    """Aviso antes de uma tarefa demorada, dentro do streaming da resposta. Quem fala/mostra a resposta o trata como
    uma mensagem à parte: é dito e aparece no chat na hora, e o resultado vem depois, em outra mensagem."""


def _pick(kind: str, options: tuple[str, ...]) -> str:
    choice = random.choice([o for o in options if o != _last.get(kind)] or list(options))
    _last[kind] = choice
    return choice


def searching() -> Notice:
    """Antes de uma pesquisa (notícias, cotação, "pesquise X"...)."""
    return Notice(_pick("search", _SEARCH))


def working() -> Notice:
    """Antes de uma tarefa pedida a outro agente (WhatsApp, criar um site, exames...)."""
    return Notice(_pick("task", _TASK))


# Tamanho da resposta falada quando ela resume o que a web ou outro agente trouxe (o resultado bruto costuma ser
# longo: cotação com variação, horário, fonte, histórico...). Vai no FIM do prompt, para valer sobre o resto.
BRIEF_ANSWER = (
    " TAMANHO — REGRA MAIS IMPORTANTE: esta resposta vai ser falada. Por padrao responda em 1 ou 2 frases curtas "
    "(ate umas 35 palavras), so com o essencial que responde a pergunta: o numero, o fato, a conclusao. Nao repita "
    "a pergunta, nao cite sites ou fontes e deixe de fora contexto, horario de atualizacao, variacoes e detalhes "
    "que nao foram pedidos. De mais detalhes so se o usuario pediu (\"detalhe\", \"explica\", \"me conta tudo\", "
    "\"quais sao\", \"lista\", \"as noticias do dia\") ou se a informacao completa for indispensavel para a "
    "resposta fazer sentido — e mesmo assim no maximo 4 ou 5 frases."
)
