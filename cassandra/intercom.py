"""Interfone: o que a pessoa fala no microfone do celular/computador (pela página) sai na caixa da Cassandra.

Enquanto está ligado, a Cassandra fica só nisso: não atende pelo nome (o microfone dela ouviria a própria caixa), a
música pausa e nenhum outro som toca — voz, bipes, alarmes, timers e avisos (SoundPlayer.play e VoiceOutput olham
active()). Ao desligar, a música volta.

O áudio chega em pedaços de ~0,2 s (PCM 16-bit mono 24 kHz, POST /api/intercom/audio): uma conexão longa não passa
pelo proxy do Netlify (corta em ~26 s). Os pedaços podem chegar fora de ordem — vão pela numeração para o pw-play.
Sem áudio por WATCHDOG_SECONDS (página fechada, celular bloqueado), desliga sozinho.
"""
from __future__ import annotations

import subprocess
import threading
import time
import uuid

RATE = 24_000
WATCHDOG_SECONDS = 12.0
_MAX_CHUNK = RATE * 2 * 2  # 2 s por pedaço, no máximo
_GAP_SECONDS = 0.4  # um pedaço que não chegou em tanto tempo fica para trás (o áudio segue sem ele)

_lock = threading.Lock()
_session: str | None = None
_proc: subprocess.Popen | None = None
_next = 0  # número do próximo pedaço a tocar
_pending: dict[int, bytes] = {}  # pedaços que chegaram antes da vez
_waiting_since = 0.0  # desde quando o próximo pedaço está atrasado
_last_audio = 0.0
_ended_at = 0.0
_speech_gen: int | None = None
_on_change = None  # chamado com True/False ao ligar/desligar (o assistente pausa/volta a música, para a escuta)


def set_listener(callback) -> None:
    global _on_change
    _on_change = callback


def active() -> bool:
    return _session is not None


def recently_active(seconds: float = 3.0) -> bool:
    """Ligado agora ou desligado há pouco (o microfone dela ainda pode ter o som da caixa na fila)."""
    return active() or time.monotonic() - _ended_at < seconds


def status() -> dict:
    return {"active": active()}


def start() -> dict:
    """Liga (ou pega a sessão de outro aparelho: só um fala por vez). Devolve a sessão para os pedaços de áudio."""
    global _session, _proc, _next, _waiting_since, _last_audio, _speech_gen
    from cassandra import speech_state  # noqa: PLC0415
    from cassandra.voice import _lead_in  # noqa: PLC0415

    with _lock:
        was = _session is not None
        _close_player()
        _session = uuid.uuid4().hex[:12]
        _next, _waiting_since, _last_audio = 0, 0.0, time.monotonic()
        _pending.clear()
        if not was:
            speech_state.cancel()  # o que ela estava fazendo para
            _speech_gen = speech_state.begin()  # o microfone dela ignora o que ouvir (é a caixa)
        try:
            _proc = subprocess.Popen(["pw-play", "--raw", "--format", "s16", "--rate", str(RATE), "--channels", "1",
                                      "--latency", "100ms", "-"], stdin=subprocess.PIPE,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _proc.stdin.write(_lead_in(RATE))  # a caixa acorda o amplificador antes da primeira palavra
            _proc.stdin.flush()
        except (OSError, ValueError) as exc:
            print(f"[INTERFONE] Não abri a saída de áudio: {exc}", flush=True)
            _proc = None
        session = _session
    if not was:
        print("[INTERFONE] Ligado.", flush=True)
        threading.Thread(target=_watchdog, args=(session,), name="interfone-vigia", daemon=True).start()
        _notify(True)
    return {"active": True, "session": session}


def stop(session: str | None = None) -> dict:
    """Desliga. Com `session`, só se ainda for essa (um aparelho não desliga o de outro que assumiu depois)."""
    global _session, _ended_at, _speech_gen
    from cassandra import speech_state  # noqa: PLC0415

    with _lock:
        if _session is None or (session and session != _session):
            return {"active": _session is not None}
        _session = None
        _ended_at = time.monotonic()
        _pending.clear()
        _close_player(drain=True)
        gen, _speech_gen = _speech_gen, None
    speech_state.end(gen)
    print("[INTERFONE] Desligado.", flush=True)
    _notify(False)
    return {"active": False}


def feed(session: str, seq: int, pcm: bytes) -> bool:
    """Um pedaço de áudio. False se a sessão não vale mais (a página deve parar)."""
    global _next, _waiting_since, _last_audio
    with _lock:
        if session != _session:
            return False
        _last_audio = time.monotonic()
        if seq < _next or len(pcm) > _MAX_CHUNK or _proc is None:
            return True  # atrasado demais (já pulamos) ou sem saída: descarta
        _pending[seq] = pcm[: len(pcm) - len(pcm) % 2]
        now = time.monotonic()
        while True:
            if _next in _pending:
                _write(_pending.pop(_next))
                _next += 1
                _waiting_since = 0.0
                continue
            if not _pending:
                break
            # falta um pedaço no meio: espera um pouco por ele e depois segue sem
            if not _waiting_since:
                _waiting_since = now
            if now - _waiting_since < _GAP_SECONDS:
                break
            _next = min(_pending)
            _waiting_since = 0.0
        return True


def _write(pcm: bytes) -> None:
    global _proc
    try:
        _proc.stdin.write(pcm)
        _proc.stdin.flush()
    except (OSError, ValueError, AttributeError):
        _proc = None


def _close_player(drain: bool = False) -> None:
    global _proc
    proc, _proc = _proc, None
    if proc is None:
        return
    try:
        proc.stdin.close()  # o pw-play toca o que já recebeu e sai
    except OSError:
        pass

    def reap() -> None:
        try:
            proc.wait(timeout=2 if drain else 0.1)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()

    threading.Thread(target=reap, name="interfone-fim", daemon=True).start()


def _watchdog(session: str) -> None:
    while True:
        time.sleep(1.0)
        with _lock:
            if session != _session:
                if _session is None:
                    return
                session = _session  # outro aparelho assumiu: segue vigiando a sessão nova
            quiet = time.monotonic() - _last_audio
        if quiet > WATCHDOG_SECONDS:
            print(f"[INTERFONE] Sem áudio há {quiet:.0f} s: desligando.", flush=True)
            stop(session)
            return


def _notify(on: bool) -> None:
    if _on_change:
        try:
            _on_change(on)
        except Exception as exc:  # noqa: BLE001
            print(f"[INTERFONE] Falhou ao avisar o assistente: {exc}", flush=True)
