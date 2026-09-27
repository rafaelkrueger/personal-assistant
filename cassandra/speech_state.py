"""Enquanto a Cassandra fala, o microfone não pode ouvi-la — senão ela se ativa sozinha e responde a si mesma, em
loop (ex.: o resultado de uma pesquisa falado em segundo plano era transcrito e virava um pedido novo). Mas dizer
o nome dela no meio da fala (ou enquanto ela executa algo) interrompe tudo e ela atende o pedido novo.

- speaking(text): contexto em volta de toda fala (voz da OpenAI/Azure/espeak, em primeiro ou segundo plano).
- busy(): True durante a fala e por ECHO_TAIL segundos depois — a soundbar Bluetooth ainda está tocando o fim do
  áudio quando o processo que toca já terminou. O gravador (vad_recorder) só procura o nome nesse período.
- is_echo(text): trava de segurança depois da transcrição: o texto repete algo que ela mesma falou há pouco?
- Interrupção: cancel() começa uma nova "geração". Falas, esperas (agentes, pesquisas) e resultados atrasados de
  gerações antigas param ou são descartados (cancelled(gen) / task_cancelled()).
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
_active: dict[int, int] = {}  # geração -> falas tocando agora (pode haver mais de uma)
_quiet_after = 0.0  # monotonic a partir do qual o microfone volta a valer
_recent: list[tuple[float, str]] = []  # (quando, texto normalizado) do que ela falou
_gen = 0  # geração atual: muda a cada interrupção
_task = threading.local()  # geração da tarefa que roda nesta thread (ver task_begin)


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", t).split())


# ── Interrupção ───────────────────────────────────────────────────────────────

def generation() -> int:
    with _lock:
        return _gen


def cancel() -> int:
    """Interrompe tudo o que está em andamento: a fala para, esperas desistem, resultados atrasados são descartados.
    O microfone volta a valer na hora (sem a cauda de eco), para ouvir o pedido novo. Devolve a geração nova."""
    global _gen, _quiet_after
    with _lock:
        _gen += 1
        _quiet_after = 0.0
        return _gen


def cancelled(gen: int) -> bool:
    with _lock:
        return gen != _gen


def task_begin(gen: int | None = None) -> int:
    """Marca a thread atual como executando um pedido da geração `gen` (padrão: a atual) — ver task_cancelled()."""
    _task.gen = generation() if gen is None else gen
    return _task.gen


def task_generation() -> int | None:
    """Geração do pedido que esta thread executa (None fora de um pedido)."""
    return getattr(_task, "gen", None)


def task_cancelled() -> bool:
    """O pedido que esta thread executa foi interrompido? (False fora de um pedido marcado com task_begin)."""
    gen = getattr(_task, "gen", None)
    return gen is not None and cancelled(gen)


# ── Fala ──────────────────────────────────────────────────────────────────────

def begin(text: str = "") -> int:
    with _lock:
        _active[_gen] = _active.get(_gen, 0) + 1
        if text:
            _remember(text)
        return _gen


def end(gen: int | None = None) -> None:
    global _quiet_after
    with _lock:
        g = _gen if gen is None else gen
        if _active.get(g):
            _active[g] -= 1
            if not _active[g]:
                del _active[g]
        if g == _gen:  # fala interrompida não deixa cauda: o microfone já está ouvindo o pedido novo
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
    gen = begin(text)
    try:
        yield gen
    finally:
        end(gen)


def busy() -> bool:
    """Ela está falando agora (ou o som ainda está saindo da caixa). Falas de gerações interrompidas não contam."""
    with _lock:
        return bool(_active.get(_gen)) or time.monotonic() < _quiet_after


def said_recently(words: list[str], seconds: float = 8.0) -> bool:
    """Ela mesma falou alguma dessas palavras (ex.: o próprio nome) nos últimos segundos? Evita que "eu sou a
    Cassandra" dito por ela conte como alguém chamando."""
    targets = {_norm(w) for w in words if w}
    with _lock:
        now = time.monotonic()
        for when, said in _recent:
            if now - when <= seconds and targets & set(said.split()):
                return True
    return False


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
