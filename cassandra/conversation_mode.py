"""Modo conversa: a Cassandra conversa de verdade, em vez de só atender pedidos.

Ligado pelo botão "Conversa" no header da UI ou por voz ("vamos conversar"). Enquanto ele está ligado:
  - ela puxa assunto, faz perguntas de volta e comenta, com respostas de papo (o estilo vai no prompt do chat);
  - espera bem mais pela pessoa (LISTEN_SECONDS em vez dos 10 s de um pedido) e aceita pausas maiores no meio
    da fala (SILENCE_SECONDS) — numa conversa a gente pensa antes de continuar;
  - se a pessoa fica quieta, ela puxa assunto (até MAX_NUDGES vezes seguidas); depois fica quietinha e volta a
    esperar o nome, sem esquecer a conversa;
  - "tchau", "chega de conversa" ou o botão desligam.
"""
from __future__ import annotations

import re
import threading
import unicodedata

LISTEN_SECONDS = 25.0
SILENCE_SECONDS = 1.3
MAX_NUDGES = 2

_lock = threading.Lock()
_active = False

STYLE = (
    "\n\nMODO CONVERSA LIGADO: o usuario quer bater papo com voce, como com uma amiga — nao so fazer pedidos. "
    "Esqueca a regra de ser objetiva: seja calorosa, curiosa e espontanea. Responda em 1 a 3 frases curtas, "
    "de fala natural, e quase sempre termine com uma pergunta ou um comentario que puxe a conversa adiante. "
    "Interesse-se pelo que ele conta (como foi o dia, planos, gostos, o que ele esta fazendo), lembre do que ele "
    "disse antes nesta conversa, de opinioes leves e conte curiosidades quando couber. Nada de listas nem de "
    "ofertas genericas de ajuda (\"posso ajudar em algo mais?\"). Pedidos normais (timer, musica, pesquisa) "
    "continuam valendo: atenda e siga o papo."
)

GREETING = ("(O usuario acabou de ligar o modo conversa.) Cumprimente de forma calorosa e puxe um assunto com uma "
            "pergunta aberta, levando em conta a hora do dia. No maximo 2 frases.")
NUDGE = ("(O usuario ficou em silencio por um tempo.) Retome a conversa: faca uma pergunta sobre algo que ele "
         "contou antes ou puxe um assunto novo e leve. Uma ou duas frases curtas, sem cobrar resposta.")
GOING_QUIET = "Vou ficar quietinha. Quando quiser continuar a conversa, é só me chamar."
STOPPED = "Tudo bem, saí do modo conversa. Foi bom conversar!"

_START = (r"\bvamos (conversar|bater (um )?papo|papear)\b", r"\b(liga|ativa|entra no|modo) (o )?modo conversa\b",
          r"\bmodo conversa\b", r"\bbora (conversar|bater um papo)\b", r"\bquero (conversar|bater (um )?papo)\b")
_STOP = (r"\b(chega|para|pare|encerra|termina|sai|desliga|acaba)( de| da| do| a| o| com a| com o| com essa| com esse"
         r"| essa| esse)? (conversa|papo|modo conversa)\b",
         r"\bsai(r)? do modo conversa\b", r"\bdesliga (o )?modo conversa\b")


def _fold(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def is_start(text: str) -> bool:
    t = _fold(text)
    return any(re.search(p, t) for p in _START) and not is_stop(text)


def is_stop(text: str) -> bool:
    t = _fold(text)
    return any(re.search(p, t) for p in _STOP)


def active() -> bool:
    return _active


def set_active(on: bool) -> bool:
    """Liga/desliga. Devolve True se mudou."""
    global _active
    with _lock:
        changed = _active != bool(on)
        _active = bool(on)
    return changed
