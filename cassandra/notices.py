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


def _pick(kind: str, options: tuple[str, ...]) -> str:
    choice = random.choice([o for o in options if o != _last.get(kind)] or list(options))
    _last[kind] = choice
    return choice


def searching() -> str:
    """Antes de uma pesquisa (notícias, cotação, "pesquise X"...)."""
    return _pick("search", _SEARCH)


def working() -> str:
    """Antes de uma tarefa pedida a outro agente (WhatsApp, criar um site, exames...)."""
    return _pick("task", _TASK)
