from __future__ import annotations

import os
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from cassandra.voice import detect_player, player_command

# Sons discretos ficam abaixo do som de ativação (volume 1.0): o de espera enquanto outro agente trabalha e o de
# desativar depois de uma resposta.
WAITING_SOUND = os.getenv("THINKING_SOUND_PATH", "assets/thinking.wav").strip() or "assets/thinking.wav"
WAITING_VOLUME = float(os.getenv("THINKING_SOUND_VOLUME", "0.3") or "0.3")
SOFT_VOLUME = float(os.getenv("SOFT_SOUND_VOLUME", "0.45") or "0.45")


class SoundPlayer:
    default: "SoundPlayer | None" = None  # o player da Cassandra (para as skills tocarem o som de espera)

    def __init__(self) -> None:
        self._backend = detect_player()  # pw-play primeiro: vai direto para a saída padrão do PipeWire
        self.enabled = True
        SoundPlayer.default = self

    def _command(self, sound_path: str, volume: float | None) -> list[str] | None:
        if not self.enabled or not self._backend:
            return None
        path = Path(sound_path)
        if not path.exists():
            return None
        command = player_command(self._backend, str(path))
        if command and volume is not None and self._backend == "pw-play":
            command[1:1] = ["--volume", f"{max(0.0, min(1.0, volume)):.2f}"]
        return command

    def play(self, sound_path: str, wait: bool = False, volume: float | None = None) -> subprocess.Popen | None:
        """Toca o som. wait=True espera terminar (para tocar vários em sequência sem sobrepor). Sem wait,
        devolve o processo (quem chamou pode interromper o som). volume: 0–1 (só no pw-play)."""
        command = self._command(sound_path, volume)
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


@contextmanager
def waiting():
    """Som baixinho em loop enquanto a Cassandra espera outro agente (pesquisa, WhatsApp...). Só começa depois
    que o aviso falado termina e para assim que o bloco acaba (o resultado vai ser falado)."""
    from cassandra import speech_state  # noqa: PLC0415

    player = SoundPlayer.default
    stop = threading.Event()
    owner = speech_state.task_generation()

    def loop() -> None:
        proc: subprocess.Popen | None = None
        try:
            while not stop.is_set():
                if owner is not None and speech_state.cancelled(owner):
                    return  # chamaram a Cassandra de novo: o pedido velho não toca mais nada
                if speech_state.busy():
                    time.sleep(0.2)  # ela ainda está falando o aviso
                    continue
                proc = player.play(WAITING_SOUND, volume=WAITING_VOLUME) if player else None
                if proc is None:
                    return
                while proc.poll() is None and not stop.is_set():
                    time.sleep(0.05)
        finally:
            if proc is not None and proc.poll() is None:
                proc.terminate()

    thread = threading.Thread(target=loop, name="som-de-espera", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=1)
