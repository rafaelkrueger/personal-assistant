from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class SoundPlayer:
    def __init__(self) -> None:
        self._backend = self._detect_backend()
        self.enabled = True

    def play(self, sound_path: str) -> None:
        if not self.enabled or not self._backend:
            return

        path = Path(sound_path)
        if not path.exists():
            return

        command = self._build_command(self._backend, str(path))
        if not command:
            return

        # Play asynchronously so it does not block assistant response.
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _detect_backend(self) -> str | None:
        candidates = ["ffplay", "mpg123", "mpv", "cvlc", "play"]
        for candidate in candidates:
            if shutil.which(candidate):
                return candidate
        return None

    @staticmethod
    def _build_command(backend: str, sound_path: str) -> list[str] | None:
        if backend == "ffplay":
            return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", sound_path]
        if backend == "mpg123":
            return ["mpg123", "-q", sound_path]
        if backend == "mpv":
            return ["mpv", "--no-video", "--really-quiet", sound_path]
        if backend == "cvlc":
            return ["cvlc", "--play-and-exit", "--quiet", sound_path]
        if backend == "play":
            return ["play", "-q", sound_path]
        return None
