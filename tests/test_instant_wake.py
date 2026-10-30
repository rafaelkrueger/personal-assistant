"""Bip na hora: o nome sozinho e claro ativa pela decisão local (sem esperar a nuvem), e a nuvem ainda pode desfazer."""
import json
import os
import shutil
import tempfile
import time
import wave

import pytest

from cassandra import input_sources, local_speech
from cassandra.input_sources import MicrophoneInputSource
from cassandra.local_speech import INSTANT_QUIET_FRAMES, INSTANT_WAIT_FRAMES, LocalSpeech, WakeStream
from cassandra.vad_recorder import LiveFrame


class _Rec:
    """Reconhecedor de mentira: o parcial só tem o texto; o resultado fechado tem tempo e confiança, como no Vosk."""

    def __init__(self, words, partial=None):
        self.words = words
        self.partial = " ".join(w["word"] for w in words) if partial is None else partial
        self.finals = 0  # resultados fechados (caros no Pi)

    def PartialResult(self):  # noqa: N802 — API do Vosk
        return json.dumps({"partial": self.partial})

    def FinalResult(self):  # noqa: N802
        self.finals += 1
        return json.dumps({"text": " ".join(w["word"] for w in self.words), "result": self.words})


def _word(word, start=0.9, end=1.5, conf=1.0):
    return {"word": word, "start": start, "end": end, "conf": conf}


def _heard_stream(words, fed=60, partial=None):
    """WakeStream que acabou de achar o nome (candidato) e cujo resultado fechado será `words`."""
    ws = WakeStream.__new__(WakeStream)
    ws.speech = LocalSpeech(["cassandra", "sandra", "alessandra"])
    ws._open, ws.heard, ws.name_start = True, True, None
    ws._texts, ws._words = [], []
    ws._fed = ws._heard_at = fed
    ws._quiet_run = 0
    ws.instant_info = None
    ws._rec = _Rec(words, partial)
    return ws


def _step(ws, quiet, since_onset=25):
    ws._fed += 1  # o feed() do quadro (o reconhecimento em si não importa aqui)
    return ws.instant(quiet, since_onset + (ws._quiet_run + 1 if quiet else 0))


def _pause(ws, frames):
    return [_step(ws, True) for _ in range(frames)]


@pytest.fixture
def conf_check(monkeypatch):
    monkeypatch.setattr(local_speech, "INSTANT_CONF_CHECK", True)


@pytest.fixture
def text_only(monkeypatch):
    monkeypatch.setattr(local_speech, "INSTANT_CONF_CHECK", False)


def test_name_alone_followed_by_a_pause_beeps_once(conf_check):
    ws = _heard_stream([_word("cassandra")])
    decisions = _pause(ws, INSTANT_QUIET_FRAMES + 5)
    assert decisions.count(True) == 1 and decisions[INSTANT_QUIET_FRAMES - 1]  # na 1ª vez que a pausa completa
    assert ws.instant_info["ok"] and ws.instant_info["conf"] == 1.0 and ws.instant_info["after_name"] is not None
    assert ws._rec.finals == 1  # o resultado é fechado uma vez só


def test_anything_but_the_clear_name_alone_waits_for_the_cloud(conf_check):
    for words, why in [
        ([_word("[unk]", 0.2, 0.8), _word("cassandra")], "não era só o nome"),  # fala antes do nome (TV, conversa)
        ([_word("sandra")], "não era só o nome"),  # variação curta
        ([_word("cassandra", conf=0.3)], "confiança"),
        ([_word("cassandra", 0.9, 1.05)], "duração"),  # curto demais para ser o nome
        ([_word("cassandra"), _word("[unk]", 1.6, 2.0)], "não era só o nome"),
    ]:
        ws = _heard_stream(words)
        assert not any(_pause(ws, INSTANT_QUIET_FRAMES + 3)), words
        assert ws.instant_info["why"].startswith(why), (words, ws.instant_info)


def test_text_only_decision_never_closes_the_result(text_only):
    ws = _heard_stream([_word("cassandra", conf=0.1)])  # sem fechar o resultado, a confiança nem é vista
    assert _pause(ws, INSTANT_QUIET_FRAMES).count(True) == 1 and ws._rec.finals == 0
    ws = _heard_stream([_word("cassandra")], partial="[unk] cassandra")
    assert not any(_pause(ws, INSTANT_QUIET_FRAMES + 2)) and ws.instant_info["why"].startswith("não era só o nome")


def test_a_long_sentence_around_the_name_never_beeps_early(text_only):
    # "Eu falei com a Cassandra ontem": o Vosk às vezes só reconhece o nome — mas a fala até a pausa é longa demais.
    ws = _heard_stream([_word("cassandra")])
    assert not any(_step(ws, True, since_onset=70) for _ in range(INSTANT_QUIET_FRAMES + 2))
    assert ws.instant_info["why"].startswith("falou")
    ws = _heard_stream([_word("cassandra")])
    assert any(_step(ws, True, since_onset=35) for _ in range(INSTANT_QUIET_FRAMES + 2))  # "Ô Cassandra!" ~1 s


def test_speech_that_goes_on_after_the_name_never_beeps_early(conf_check):
    ws = _heard_stream([_word("cassandra")])
    assert not any(_step(ws, False) for _ in range(INSTANT_WAIT_FRAMES + 2))
    assert ws.instant_info == {"ok": False, "why": "a fala continuou depois do nome"}
    assert not any(_pause(ws, INSTANT_QUIET_FRAMES + 2)) and ws._rec.finals == 0


def test_no_decision_before_the_candidate():
    ws = _heard_stream([_word("cassandra")])
    ws.heard = False
    assert not any(_pause(ws, 30)) and ws.instant_info is None


def _src():
    m = MicrophoneInputSource.__new__(MicrophoneInputSource)
    m.assistant_name = "cassandra"
    m.wake_words = ["cassandra", "sandra", "alessandra"]
    m.transcription_prompt = ""
    return m


def test_cloud_undoes_the_instant_beep_only_when_it_heard_something_else():
    m = _src()
    for heard in ["Fernanda.", "Cansada.", "Amanda!", "E agora a previsão do tempo para amanhã.", "Casa nova."]:
        assert m._wake_denied(heard), heard
    for heard in ["Cassandra.", "Casandara?", "Cacandra, que horas são?", "Sandra!", "", "Obrigado por assistir!",
                  "Cassandra, toca música."]:
        assert not m._wake_denied(heard), heard


class _FakeRecorder:
    """Gravador de mentira: passa N quadros pelo on_frame (com o estado ao vivo) e devolve um WAV."""

    def __init__(self, frames=60, quiet_from=40):
        self.frames, self.quiet_from = frames, quiet_from
        self.last_barged, self.last_peak, self.live = False, 1500.0, None

    def record_utterance(self, on_frame=None, **_):
        for i in range(self.frames):
            self.live = LiveFrame(quiet=i >= self.quiet_from, voiced=min(i, 20), peak=1500.0, threshold=400.0,
                                  onset=max(0, i - 15))
            on_frame(b"\x00\x00" * 480)
            time.sleep(0.002)
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"\x00\x00" * 480 * self.frames)
        return path


class _FakeStream:
    """WakeStream de mentira: candidato no quadro 35, decisão local no 45."""

    def __init__(self, instant_ok=True):
        self.n, self.heard, self.name_start, self.instant_ok = 0, False, None, instant_ok
        self.instant_info = None

    def feed(self, _frame):
        self.n += 1
        if self.n == 35:
            self.heard = True
            return True
        return False

    def instant(self, quiet, since_onset=0):
        if self.n == 45 and quiet and self.instant_ok:
            self.instant_info = {"ok": True, "why": "", "conf": 1.0, "seconds": 0.6, "after_name": 0.3}
            return True
        return False

    def close(self):
        return self.heard, True, "cassandra"


class _FakeLocal:
    def __init__(self, stream):
        self._stream = stream

    def available(self):
        return True

    def stream(self):
        return self._stream


def _run(transcripts, instant_ok=True):
    """Uma chamada inteira pelo _capture_and_transcribe; devolve (texto, bipes, bipes desfeitos)."""
    m = _src()
    m.local, m.local_wake, m.debug = _FakeLocal(_FakeStream(instant_ok)), True, False
    m._recorder, m.interrupt_event = _FakeRecorder(), None
    m._caller_level = m._caller_at = 0.0
    m._signaled = m._instant = m._cloud_ok = m._candidate = False
    m._candidate_at, m._early = 0.0, ("", 0)
    wakes, cancels = [], []
    m.on_wake, m.on_wake_cancel = lambda: wakes.append(1), lambda: cancels.append(1)
    m.on_candidate = m.on_speech = m.on_barge = None
    calls = []

    def transcribe(_path):
        calls.append(1)
        return transcripts[min(len(calls), len(transcripts)) - 1]

    m._transcribe = transcribe
    m._warm_transcription = lambda: None
    old = input_sources._EARLY_CHECKS
    input_sources._EARLY_CHECKS = (0.01, 0.02)
    try:
        text = m._capture_and_transcribe(0.5, wake_phase=True)
    finally:
        input_sources._EARLY_CHECKS = old
    return text, len(wakes), len(cancels)


def test_clear_name_beeps_locally_and_the_cloud_confirms():
    assert _run(["Cassandra."]) == ("cassandra", 1, 0)


def test_instant_beep_is_undone_when_the_cloud_hears_another_word():
    assert _run(["Fernanda."]) == ("", 1, 1)


def test_instant_beep_stands_when_the_cloud_has_nothing_to_say():
    assert _run([""]) == ("cassandra", 1, 0)  # sem internet/sem texto: vale o Vosk, a sessão abre


def test_without_the_local_decision_the_cloud_still_decides():
    assert _run(["Fernanda."], instant_ok=False) == ("", 0, 0)
    assert _run(["Cassandra, que horas são?"], instant_ok=False) == ("cassandra, que horas são", 1, 0)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="precisa do ffmpeg")
def test_sounds_are_decoded_once_without_the_leading_silence(tmp_path):
    import numpy as np

    from cassandra.voice import SpeakerWaker

    rate = 48000
    tone = (np.sin(2 * np.pi * 880 * np.arange(int(0.2 * rate)) / rate) * 10000).astype(np.int16)
    path = tmp_path / "bip.wav"
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(np.zeros(int(0.1 * rate), np.int16).tobytes() + tone.tobytes())
    pcm = np.frombuffer(SpeakerWaker()._decode(str(path), 0.5), dtype=np.int16)
    assert abs(len(pcm) / rate - 0.205) < 0.01  # o silêncio do começo saiu (fica 5 ms antes do som)
    assert abs(int(np.abs(pcm).max()) - 5000) < 100  # volume aplicado


def test_cue_plays_through_the_open_channel(monkeypatch):
    from cassandra import voice

    written = []

    class _Pipe:
        def write(self, data):
            written.append(bytes(data))
            time.sleep(0.001)
            return len(data)

        def fileno(self):
            raise OSError

        def close(self):
            pass

    class _Proc:
        stdin = _Pipe()

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(voice.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(voice.subprocess, "Popen", lambda *a, **k: _Proc())
    waker = voice.SpeakerWaker()
    beep = b"\x10\x27" * 4800  # 0,1 s
    waker._sounds[("on.mp3", 1.0)] = beep
    assert not waker.cue("off.mp3")  # não carregado: o chamador usa o player normal
    assert waker.cue("on.mp3")  # canal fechado: abre, sopro antes (a caixa dormia) e o bip
    deadline = time.monotonic() + 3
    while not any(beep in w for w in written) and time.monotonic() < deadline:
        time.sleep(0.01)
    first = next(w for w in written if beep in w)
    assert len(first) - len(beep) == int(waker.RATE * waker.LEAD) * 2  # 0,5 s de sopro na frente
    waker._since -= waker.WARM  # canal aberto há tempo: a caixa já acordou
    written.clear()
    assert waker.cue("on.mp3")
    deadline = time.monotonic() + 3
    while beep not in written and time.monotonic() < deadline:
        time.sleep(0.01)
    assert beep in written  # sem sopro na frente: sai na hora
    with waker._lock:
        waker._until = 0.0


def test_a_piece_of_the_context_prompt_is_a_made_up_transcription():
    from cassandra.config import Settings

    m = _src()
    m.transcription_prompt = Settings.transcription_prompt
    # ouvido no Pi com o áudio do bip/ruído logo depois do nome: virou pedido
    assert m._hallucinated("pedidos de casa como música no Spotify, TV, Netflix, alarmes, lembretes")
    assert m._hallucinated("Música no Spotify, TV, Netflix, alarmes, lembretes.")
    for real in ["Cassandra, toca música no Spotify.", "Liga a TV e abre a Netflix.", "Pergunta pro Pulse quanto eu dormi.",
                 "Coloca um alarme e um lembrete pras sete."]:
        assert not m._hallucinated(real), real
