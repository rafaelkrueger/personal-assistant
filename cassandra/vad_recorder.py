"""VAD-based audio recorder: captures a complete utterance using energy detection."""
from __future__ import annotations

import math
import os
import struct
import tempfile
import threading
import wave

from cassandra.mic_monitor import monitor

SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit PCM
FRAME_MS = 30  # frame duration in milliseconds
FRAME_SIZE = int(SAMPLE_RATE * FRAME_MS / 1000)  # samples per frame = 480
# Taxas tentadas ao abrir o microfone. Muitos microfones USB só gravam a 48 kHz: abre na taxa que ele aceita e
# converte para 16 kHz (o que a transcrição e o Vosk esperam).
_CAPTURE_RATES = (16_000, 48_000, 44_100, 32_000, 22_050, 96_000)


def _to_16k(frame: bytes, rate: int) -> bytes:
    """PCM 16-bit mono na taxa do microfone -> 16 kHz."""
    if rate == SAMPLE_RATE:
        return frame
    import numpy as np  # noqa: PLC0415

    samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
    if rate % SAMPLE_RATE == 0:  # 48 kHz, 32 kHz...: média de cada grupo (filtro passa-baixa simples)
        factor = rate // SAMPLE_RATE
        samples = samples[: len(samples) // factor * factor].reshape(-1, factor).mean(axis=1)
    else:
        target = int(round(len(samples) * SAMPLE_RATE / rate))
        samples = np.interp(np.linspace(0, len(samples) - 1, target), np.arange(len(samples)), samples)
    return np.clip(samples, -32768, 32767).astype(np.int16).tobytes()


class VadRecorder:
    """Records audio continuously, returning one complete utterance per call.

    Uses energy-based Voice Activity Detection:
    - Waits for audio energy to exceed `energy_threshold` (speech start)
    - Records until energy stays below threshold for `silence_duration` seconds
    - Keeps a short pre-roll buffer so the beginning of speech is never clipped
    - Stops unconditionally after `max_duration` seconds

    Args:
        energy_threshold: RMS energy level that distinguishes speech from silence.
            Typical ambient noise is 50-200; speech is 500-5000+. Tune via MIC_DEBUG.
        silence_duration: Seconds of sustained silence required to end recording.
        max_duration: Hard cap on recording length in seconds.
        pre_roll_frames: Number of 30ms frames to keep before speech onset (~200ms).
    """

    def __init__(
        self,
        energy_threshold: int = 400,
        silence_duration: float = 1.2,
        max_duration: float = 30.0,
        pre_roll_frames: int = 7,
    ) -> None:
        self.energy_threshold = energy_threshold
        self.silence_duration = silence_duration
        self.max_duration = max_duration
        self.pre_roll_frames = pre_roll_frames
        self._pa = None
        monitor.set(threshold=energy_threshold)
        self._rate: int | None = None  # a taxa que o microfone atual aceitou

    def _ensure_pyaudio(self):
        if self._pa is None:
            try:
                import pyaudio  # noqa: PLC0415
            except ImportError as exc:
                raise RuntimeError(
                    "pyaudio nao instalado. Execute: pip install pyaudio"
                ) from exc
            self._pa = pyaudio.PyAudio()
        return self._pa

    @staticmethod
    def _input_device(pa) -> int | None:
        """Prefere a entrada do PipeWire/Pulse (converte a taxa e segue o microfone padrão, inclusive um recém
        plugado — precisa do pacote pipewire-alsa); senão, o primeiro aparelho de hardware com entrada."""
        devices = [pa.get_device_info_by_index(i) for i in range(pa.get_device_count())]
        inputs = [d for d in devices if d.get("maxInputChannels", 0) > 0]
        for name in ("pipewire", "pulse", "default"):
            for d in inputs:
                if d.get("name") == name:
                    return int(d["index"])
        return int(inputs[0]["index"]) if inputs else None

    def _open_stream(self, pa, pyaudio):
        """Abre o microfone na 1ª taxa que ele aceitar. Devolve (stream, taxa, amostras por quadro de 30 ms)."""
        device = self._input_device(pa)
        rates = list(_CAPTURE_RATES)
        if device is not None:
            default = int(pa.get_device_info_by_index(device).get("defaultSampleRate") or 0)
            if default:
                rates.append(default)
        if self._rate:
            rates.insert(0, self._rate)
        last_error: Exception | None = None
        for rate in dict.fromkeys(rates):
            frames = int(rate * FRAME_MS / 1000)
            try:
                stream = pa.open(format=pyaudio.paInt16, channels=CHANNELS, rate=rate, input=True,
                                 input_device_index=device, frames_per_buffer=frames)
            except Exception as exc:  # noqa: BLE001 — "Invalid sample rate" e afins: tenta a próxima
                last_error = exc
                continue
            if rate != self._rate:
                note = "" if rate == SAMPLE_RATE else f" (convertido para {SAMPLE_RATE} Hz)"
                print(f"[MIC] Microfone aberto a {rate} Hz{note}", flush=True)
                try:
                    name = pa.get_device_info_by_index(device).get("name", "") if device is not None else ""
                except Exception:  # noqa: BLE001
                    name = ""
                monitor.set(device=name, rate=rate)
                monitor.event("status", f"Microfone aberto: {name or 'padrão'} a {rate} Hz{note}")
            self._rate = rate
            return stream, rate, frames
        raise last_error or RuntimeError("nenhum microfone")

    @staticmethod
    def _rms(frame: bytes) -> float:
        count = len(frame) // 2
        if not count:
            return 0.0
        shorts = struct.unpack(f"{count}h", frame)
        return math.sqrt(sum(s * s for s in shorts) / count)

    def record_utterance(
        self,
        silence_duration: float | None = None,
        interrupt_event: threading.Event | None = None,
    ) -> str | None:
        """Block until speech is detected, then record until silence.

        Args:
            silence_duration: Override the instance silence_duration for this call.
                Useful for wake-word phase (short) vs command phase (longer).
            interrupt_event: When set by an external thread (e.g. a fired timer),
                recording stops immediately and returns None so the caller can
                handle the interrupt before the next listening window.

        Returns:
            Absolute path to a temporary WAV file containing the utterance,
            or None if no speech was detected or recording was interrupted.
        """
        import pyaudio  # noqa: PLC0415

        pa = self._ensure_pyaudio()
        effective_silence = silence_duration if silence_duration is not None else self.silence_duration
        max_frames = int(self.max_duration * 1000 / FRAME_MS)
        silence_frames_needed = int(effective_silence * 1000 / FRAME_MS)

        stream, rate, device_frames = self._open_stream(pa, pyaudio)

        pre_roll: list[bytes] = []
        recorded: list[bytes] = []
        speaking = False
        silent_frames = 0
        interrupted = False

        try:
            for _ in range(max_frames):
                if interrupt_event and interrupt_event.is_set():
                    interrupted = True
                    break

                frame = _to_16k(stream.read(device_frames, exception_on_overflow=False), rate)
                energy = self._rms(frame)
                monitor.level(energy)

                if not speaking:
                    pre_roll.append(frame)
                    if len(pre_roll) > self.pre_roll_frames:
                        pre_roll.pop(0)
                    if energy > self.energy_threshold:
                        speaking = True
                        recorded.extend(pre_roll)
                        pre_roll.clear()
                        recorded.append(frame)
                        silent_frames = 0
                else:
                    recorded.append(frame)
                    if energy < self.energy_threshold:
                        silent_frames += 1
                        if silent_frames >= silence_frames_needed:
                            break
                    else:
                        silent_frames = 0
        finally:
            stream.stop_stream()
            stream.close()

        if interrupted:
            return None

        if not recorded:
            return None
        peak = max((self._rms(f) for f in recorded), default=0)
        monitor.event("heard", f"Som captado: {len(recorded) * FRAME_MS / 1000:.1f} s (pico {peak:.0f}, "
                               f"limite {self.energy_threshold})")

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        with wave.open(tmp.name, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(SAMPLE_WIDTH)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(b"".join(recorded))

        return tmp.name

    def close(self) -> None:
        self._rate = None  # outro microfone pode ser plugado: descobre a taxa de novo
        if self._pa is not None:
            self._pa.terminate()
            self._pa = None
