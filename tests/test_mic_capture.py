"""Gravação do microfone: filtro de graves, fim da fala relativo à voz de quem fala e limites depois do nome."""
import math
import sys
import types

import numpy as np
import pytest

from cassandra import vad_recorder as vr

RATE = 16_000


def _voice(seconds: float, rms: float, f0: float = 140.0) -> np.ndarray:
    """Som com "tom de voz" (harmônicos de f0, como uma vogal) — passa no _is_voiced."""
    t = np.arange(int(seconds * RATE)) / RATE
    x = sum(np.sin(2 * np.pi * f0 * k * t) for k in range(1, 12))
    return x * rms / np.sqrt(np.mean(x * x))


def _hum(seconds: float, rng) -> np.ndarray:
    """O "chiado" do microfone USB: ronco de 50 Hz e de ~12 Hz + um pouco de chiado de verdade."""
    t = np.arange(int(seconds * RATE)) / RATE
    return 380 * np.sin(2 * np.pi * 50 * t) + 250 * np.sin(2 * np.pi * 12 * t) + rng.normal(0, 120, len(t))


class _Stream:
    def __init__(self, audio: np.ndarray) -> None:
        self.a = np.clip(audio, -32768, 32767).astype(np.int16)
        self.pos = 0

    def read(self, n, exception_on_overflow=False):  # noqa: ARG002
        if self.pos + n > len(self.a):
            raise EOFError
        chunk = self.a[self.pos:self.pos + n]
        self.pos += n
        return chunk.tobytes()

    def stop_stream(self):
        pass

    def close(self):
        pass


@pytest.fixture
def recorder(monkeypatch):
    fake = types.ModuleType("pyaudio")
    fake.paInt16 = 8
    fake.PyAudio = lambda: types.SimpleNamespace(terminate=lambda: None)
    monkeypatch.setitem(sys.modules, "pyaudio", fake)
    from cassandra import audio_routes

    monkeypatch.setattr(audio_routes, "mic_choice", lambda: "usb")

    def make(audio):
        rec = vr.VadRecorder(energy_threshold=400, silence_duration=0.6, max_duration=30.0)
        stream = _Stream(audio)
        rec._stream = (stream, RATE, 480)
        rec._opened_choice = "usb"
        rec._source_checked = 1e18
        return rec, stream

    return make


def test_high_pass_matches_the_textbook_filter_and_removes_the_hum():
    rng = np.random.default_rng(0)
    x = (rng.standard_normal(RATE) * 3000).astype(np.int16)
    a = math.exp(-2 * math.pi * 100 / RATE)
    b = (1 + a) / 2
    want = x.astype(np.float64)
    for _ in range(2):  # dois estágios de 1ª ordem, amostra por amostra
        y = np.zeros_like(want)
        x1 = y1 = 0.0
        for n, v in enumerate(want):
            y1 = a * y1 + b * (v - x1)
            x1 = v
            y[n] = y1
        want = y
    hp = vr._HighPass(100)
    got = np.concatenate([np.frombuffer(hp(x[i:i + 480].tobytes()), np.int16) for i in range(0, RATE - 479, 480)])
    assert np.abs(got - np.clip(np.rint(want[:len(got)]), -32768, 32767)).max() == 0

    def rms_after(sig):
        hp = vr._HighPass(100)
        out = np.concatenate([np.frombuffer(hp(sig[i:i + 480].astype(np.int16).tobytes()), np.int16)
                              for i in range(0, len(sig) - 479, 480)]).astype(np.float64)[RATE // 4:]
        return float(np.sqrt(np.mean(out ** 2)))

    t = np.arange(RATE) / RATE
    assert rms_after(1000 * np.sin(2 * np.pi * 50 * t)) < 0.3 * 707  # ronco de 50 Hz: some quase todo
    assert rms_after(1000 * np.sin(2 * np.pi * 1000 * t)) > 0.98 * 707  # a voz (1 kHz) fica


def test_voiced_check_is_the_same_with_the_faster_autocorrelation():
    def old(frame):
        x = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        x = x - x.mean()
        if float((x * x).sum()) < 1e4:
            return False
        ac = np.correlate(x, x, "full")[len(x) - 1:]
        if float(ac[40:201].max() / ac[0]) < vr.VOICED_PERIODICITY:
            return False
        spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
        return float(spec.max() / spec.sum()) < vr.VOICED_MAX_TONAL

    rng = np.random.default_rng(1)
    sigs = [_voice(0.5, 2000), rng.normal(0, 800, 8000), 3000 * np.sin(np.arange(8000) / 4.0), _hum(0.5, rng)]
    for sig in sigs:
        for i in range(0, len(sig) - 479, 480):
            frame = sig[i:i + 480].astype(np.int16).tobytes()
            assert vr._is_voiced(frame) == old(frame)


def test_recording_ends_on_the_pause_even_with_the_mic_hum(recorder):
    rng = np.random.default_rng(2)
    audio = np.concatenate([_hum(4.0, rng), _hum(1.2, rng) + _voice(1.2, 2500), _hum(6.0, rng)])
    rec, stream = recorder(audio)
    path = rec.record_utterance(silence_duration=0.6)
    assert path is not None
    end = stream.pos / RATE
    assert end < 5.2 + 0.6 + 0.4  # fim da fala + a pausa (antes: o ronco passava do limite e ela não terminava)


def test_recording_ends_when_only_the_quieter_tv_is_left(recorder):
    rng = np.random.default_rng(3)
    tv = lambda s: _voice(s, 450, f0=210) + rng.normal(0, 150, int(s * RATE))  # noqa: E731
    audio = np.concatenate([tv(4.0), tv(1.5) + _voice(1.5, 3000), tv(8.0)])
    rec, stream = recorder(audio)
    assert rec.record_utterance(silence_duration=0.6) is not None
    assert stream.pos / RATE < 5.5 + 0.6 + 0.5  # a TV, bem mais baixa que a pessoa, conta como pausa


def test_after_the_name_the_recording_is_capped(recorder, monkeypatch):
    monkeypatch.setattr(vr, "AFTER_NAME_MAX_S", 3.0)
    rng = np.random.default_rng(4)
    audio = np.concatenate([_hum(4.0, rng), _voice(14.0, 3000) + _hum(14.0, rng)])  # som alto sem parar
    rec, stream = recorder(audio)
    assert rec.record_utterance(silence_duration=0.6, on_frame=lambda f: True) is not None
    assert stream.pos / RATE < 4.0 + 3.0 + 0.5  # o nome veio logo no começo: no máximo 3 s depois dele


def test_session_ignores_sound_much_quieter_than_the_caller(recorder):
    rng = np.random.default_rng(5)
    audio = np.concatenate([_hum(4.0, rng), _voice(2.0, 700) + _hum(2.0, rng), _hum(3.0, rng)])
    rec, _stream = recorder(audio)
    assert rec.record_utterance(silence_duration=0.6, max_wait=8.0, min_level=1500) is None
    rec, _stream = recorder(audio)
    assert rec.record_utterance(silence_duration=0.6, max_wait=8.0, min_level=400) is not None
    assert rec.last_peak > 400


def test_azure_key_rejected_until_it_changes(monkeypatch):
    from cassandra import voice

    key = {"k": "chave-velha"}
    monkeypatch.setattr(voice, "_azure_config", lambda: (key["k"], "brazilsouth", "pt-BR-ElzaNeural"))
    monkeypatch.setattr(voice, "_azure_rejected", "")
    assert not voice.azure_key_rejected()
    voice.reject_azure_key("chave-velha")
    assert voice.azure_key_rejected()  # 401: nem tenta mais (a voz e a transcrição vão direto pela OpenAI)
    key["k"] = "chave-nova"
    assert not voice.azure_key_rejected()  # trocou nas Configurações: tenta de novo


def test_early_check_starts_at_the_name_said_over_the_tv():
    import threading
    import wave

    from cassandra import input_sources
    from cassandra.input_sources import MicrophoneInputSource

    m = MicrophoneInputSource.__new__(MicrophoneInputSource)
    m.assistant_name = "cassandra"
    seconds = []

    def transcribe(path):
        with wave.open(path, "rb") as wf:
            seconds.append(wf.getnframes() / wf.getframerate())
        return "Cassandra"

    m._transcribe = transcribe
    m._signal_wake = lambda: None
    frames = [b"\x00\x00" * 480] * 100  # 3 s gravados: TV até ~2 s, o nome a partir de 2,0 s
    stream = types.SimpleNamespace(name_start=2.0)
    old, input_sources._EARLY_CHECKS = input_sources._EARLY_CHECKS, (0.01,)
    try:
        m._confirm_early(frames, threading.Event(), threading.Event(), stream)
    finally:
        input_sources._EARLY_CHECKS = old
    assert seconds and abs(seconds[0] - 1.26) < 0.05  # de 1,75 s (0,25 s antes do nome) até o fim


def test_capture_thread_keeps_the_audio_while_processing_lags(monkeypatch):
    import time as _time

    from cassandra import speech_state

    class Slow:
        def __init__(self):
            self.n = 0

        def read(self, frames, exception_on_overflow=False):  # noqa: ARG002
            _time.sleep(0.01)  # o aparelho entrega um quadro a cada 10 ms
            self.n += 1
            if self.n > 60:
                raise OSError("desplugado")
            return self.n.to_bytes(2, "little") * frames

        def stop_stream(self):
            pass

        def close(self):
            pass

    calls = {"n": 0}

    def busy():
        calls["n"] += 1
        return calls["n"] <= 5  # ela falava nos 5 primeiros quadros

    monkeypatch.setattr(speech_state, "busy", busy)
    cap = vr._CaptureThread(Slow(), 4)
    _time.sleep(0.25)  # o processamento travou: 25 quadros chegaram enquanto isso
    got = []
    with pytest.raises(OSError):
        while True:
            data, was_busy = cap.read_frame(timeout=2)
            got.append((int.from_bytes(data[:2], "little"), was_busy))
    assert [n for n, _ in got] == list(range(1, 61))  # nenhum quadro perdido, na ordem
    assert [b for _, b in got[:7]] == [True] * 5 + [False] * 2  # a marca é a da hora da captura
    cap.close()


def test_loudness_is_measured_only_in_the_voice_band():
    t = np.arange(480) / RATE
    tone = lambda hz: (1000 * np.sin(2 * np.pi * hz * t)).astype(np.int16).tobytes()  # noqa: E731
    assert abs(vr._band_rms(tone(1000)) - vr.VadRecorder._rms(tone(1000))) < 2  # na faixa: o mesmo RMS
    assert vr._band_rms(tone(120)) < 15  # motor / zumbido elétrico: fora (-35 dB ou mais)
    assert vr._band_rms(tone(6000)) < 5  # chiado agudo: fora
