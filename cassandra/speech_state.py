"""Enquanto a Cassandra fala, o microfone não pode ouvi-la — senão ela se ativa sozinha e responde a si mesma, em
loop (ex.: o resultado de uma pesquisa falado em segundo plano era transcrito e virava um pedido novo).

- speaking(text): contexto em volta de toda fala (voz da OpenAI/Azure/espeak, em primeiro ou segundo plano).
- busy(): True durante a fala e por ECHO_TAIL segundos depois — a soundbar Bluetooth ainda está tocando o fim do
  áudio quando o processo que toca já terminou. O gravador (vad_recorder) descarta tudo o que ouve nesse período.
- is_echo(text): trava de segurança depois da transcrição: o texto repete algo que ela mesma falou há pouco?
"""
from __future__ import annotations

import os
import re
import threading
import time
import unicodedata
from contextlib import contextmanager
from difflib import SequenceMatcher

ECHO_TAIL = float(os.getenv("ECHO_TAIL_SECONDS", "1.5") or "1.5")
_RECENT_SECONDS = 60.0  # por quanto tempo uma fala dela conta para is_echo()

_lock = threading.Lock()
_active = 0  # falas tocando agora (pode haver mais de uma: chat web em segundo plano + resposta por voz)
_quiet_after = 0.0  # monotonic a partir do qual o microfone volta a valer
_recent: list[tuple[float, str]] = []  # (quando, texto normalizado) do que ela falou


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", t).split())


def begin(text: str = "") -> None:
    global _active
    with _lock:
        _active += 1
        if text:
            _remember(text)


def end() -> None:
    global _active, _quiet_after
    with _lock:
        _active = max(0, _active - 1)
        _quiet_after = max(_quiet_after, time.monotonic() + ECHO_TAIL)


def remember(text: str) -> None:
    """Registra o texto de uma fala já em andamento (ex.: frases de uma resposta em streaming)."""
    with _lock:
        _remember(text)


def _remember(text: str) -> None:
    now = time.monotonic()
    norm = _norm(text)
    if norm:
        _recent.append((now, norm))
    while _recent and now - _recent[0][0] > _RECENT_SECONDS:
        _recent.pop(0)


@contextmanager
def speaking(text: str = ""):
    begin(text)
    try:
        yield
    finally:
        end()


def busy() -> bool:
    """Ela está falando agora (ou o som ainda está saindo da caixa)."""
    with _lock:
        return _active > 0 or time.monotonic() < _quiet_after


def is_echo(text: str) -> bool:
    """A transcrição é a própria voz dela (algo que ela falou nos últimos 60 s)?"""
    heard = _norm(text)
    if len(heard) < 8:  # "sim", "para", "ok": curto demais para comparar com segurança
        return False
    with _lock:
        spoken = [t for when, t in _recent if time.monotonic() - when <= _RECENT_SECONDS]
    words = heard.split()
    for said in spoken:
        if heard in said:
            return True
        # A transcrição do eco sai com pequenas diferenças ("40" x "quarenta"): quase todas as palavras ouvidas
        # estão na fala dela. Uma pergunta nova sobre o mesmo assunto ("qual a umidade do ar hoje?") não passa.
        said_words = set(said.split())
        if len(words) >= 3 and sum(w in said_words for w in words) / len(words) >= 0.85:
            return True
        if len(words) >= 3 and SequenceMatcher(None, heard, said).ratio() >= 0.85:
            return True
    return False
