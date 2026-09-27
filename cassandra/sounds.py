from __future__ import annotations

import subprocess
from pathlib import Path

from cassandra.voice import detect_player, player_command


class SoundPlayer:
    def __init__(self) -> None:
        self._backend = detect_player()  # pw-play primeiro: vai direto para a saída padrão do PipeWire
        self.enabled = True

    def play(self, sound_path: str, wait: bool = False) -> None:
        """Toca o som. wait=True espera terminar (para tocar vários em sequência sem sobrepor)."""
        if not self.enabled or not self._backend:
            return

        path = Path(sound_path)
        if not path.exists():
            return

        command = player_command(self._backend, str(path))
        if not command:
            return

        if wait:
            try:
                subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
            except subprocess.TimeoutExpired:
                pass
            return

        # Play asynchronously so it does not block assistant response.
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
