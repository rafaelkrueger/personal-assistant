"""VAD-based audio recorder: captures a complete utterance using energy detection."""
from __future__ import annotations

import math
import os
import struct
import tempfile
import threading
import wave

SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit PCM
FRAME_MS = 30  # frame duration in milliseconds
FRAME_SIZE = int(SAMPLE_RATE * FRAME_MS / 1000)  # samples per frame = 480


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

        stream = pa.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=FRAME_SIZE,
        )

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

                frame = stream.read(FRAME_SIZE, exception_on_overflow=False)
                energy = self._rms(frame)

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

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        with wave.open(tmp.name, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(SAMPLE_WIDTH)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(b"".join(recorded))

        return tmp.name

    def close(self) -> None:
        if self._pa is not None:
            self._pa.terminate()
            self._pa = None
