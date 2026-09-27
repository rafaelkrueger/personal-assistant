from __future__ import annotations

import subprocess
from pathlib import Path

from cassandra.voice import detect_player, player_command


class SoundPlayer:
    def __init__(self) -> None:
        self._backend = detect_player()  # pw-play primeiro: vai direto para a saída padrão do PipeWire
        self.enabled = True

    def play(self, sound_path: str, wait: bool = False) -> subprocess.Popen | None:
        """Toca o som. wait=True espera terminar (para tocar vários em sequência sem sobrepor). Sem wait,
        devolve o processo (quem chamou pode interromper o som)."""
        if not self.enabled or not self._backend:
            return None

        path = Path(sound_path)
        if not path.exists():
            return None

        command = player_command(self._backend, str(path))
        if not command:
            return None

        if wait:
            try:
                subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
            except subprocess.TimeoutExpired:
                pass
            return None

        # Play asynchronously so it does not block assistant response.
        return subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
