"""Keeps the Bluetooth speaker awake by playing a near-silent tone periodically.

Why this is needed:
  Most Bluetooth speakers shut off after 3-10 min of no audio activity.
  aplay sends audio to ALSA directly, bypassing PulseAudio/PipeWire where
  Bluetooth sinks live. We must use paplay / ffplay / mpg123 so the audio
  actually reaches the BT speaker.
  Pure silence is sometimes ignored; a barely-audible 18 kHz sine is safer.
"""
from __future__ import annotations

import math
import shutil
import struct
import subprocess
import tempfile
import threading
import wave


class SpeakerKeepAlive:
    """Plays a near-silent tone every `interval_seconds` (default 2 min)."""

    def __init__(self, interval_seconds: int = 120) -> None:
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._backend = self._detect_backend()
        self._wav_path = self._create_tone_wav()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._backend is None or self._wav_path is None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="speaker-keepalive"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            self._play()

    def _play(self) -> None:
        if not self._wav_path or not self._backend:
            return
        cmd = self._build_command(self._backend, self._wav_path)
        if cmd:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # ------------------------------------------------------------------
    @staticmethod
    def _detect_backend() -> str | None:
        # Prefer PulseAudio/PipeWire-aware players so BT speakers receive audio
        for candidate in ["paplay", "ffplay", "mpg123", "mpv", "cvlc", "play"]:
            if shutil.which(candidate):
                return candidate
        return None

    @staticmethod
    def _build_command(backend: str, wav_path: str) -> list[str] | None:
        if backend == "paplay":
            return ["paplay", "--volume=100", wav_path]   # ~0.15% volume
        if backend == "ffplay":
            return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet",
                    "-af", "volume=0.002", wav_path]
        if backend == "mpg123":
            return ["mpg123", "-q", "--scale", "100", wav_path]
        if backend == "mpv":
            return ["mpv", "--no-video", "--really-quiet",
                    "--volume=1", wav_path]
        if backend == "cvlc":
            return ["cvlc", "--play-and-exit", "--quiet", wav_path]
        if backend == "play":
            return ["play", "-q", wav_path]
        return None

    @staticmethod
    def _create_tone_wav() -> str | None:
        """Creates a 1-second 18 kHz sine wave at amplitude 200/32767 (~0.6%)."""
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            sample_rate = 44100
            freq = 18000          # 18 kHz — above most people's hearing range
            amplitude = 200       # out of 32767 — virtually inaudible
            n_samples = sample_rate  # 1 second

            frames = struct.pack(
                f"<{n_samples}h",
                *(
                    int(amplitude * math.sin(2 * math.pi * freq * i / sample_rate))
                    for i in range(n_samples)
                ),
            )

            with wave.open(tmp.name, "w") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(frames)

            return tmp.name
        except Exception:
            return None
