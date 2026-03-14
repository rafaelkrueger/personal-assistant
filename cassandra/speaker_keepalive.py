"""Keeps the Bluetooth speaker awake by playing inaudible silence periodically."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
import time
import wave


class SpeakerKeepAlive:
    """Plays a short silent WAV every `interval_seconds` to prevent speaker auto-off."""

    def __init__(self, interval_seconds: int = 240) -> None:
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._backend = self._detect_backend()
        self._silent_wav = self._create_silent_wav()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._backend is None or self._silent_wav is None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="speaker-keepalive")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            self._play_silence()

    def _play_silence(self) -> None:
        if not self._silent_wav or not self._backend:
            return
        cmd = self._build_command(self._backend, self._silent_wav)
        if cmd:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # ------------------------------------------------------------------
    @staticmethod
    def _detect_backend() -> str | None:
        for candidate in ["aplay", "ffplay", "mpv", "cvlc", "play"]:
            if shutil.which(candidate):
                return candidate
        return None

    @staticmethod
    def _build_command(backend: str, wav_path: str) -> list[str] | None:
        if backend == "aplay":
            return ["aplay", "-q", wav_path]
        if backend == "ffplay":
            return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", wav_path]
        if backend == "mpv":
            return ["mpv", "--no-video", "--really-quiet", wav_path]
        if backend == "cvlc":
            return ["cvlc", "--play-and-exit", "--quiet", wav_path]
        if backend == "play":
            return ["play", "-q", wav_path]
        return None

    @staticmethod
    def _create_silent_wav() -> str | None:
        """Creates a 0.3-second silent mono 16-bit WAV and returns its path."""
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            sample_rate = 44100
            duration_samples = int(sample_rate * 0.3)
            with wave.open(tmp.name, "w") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(sample_rate)
                wf.writeframes(b"\x00\x00" * duration_samples)
            return tmp.name
        except Exception:
            return None
