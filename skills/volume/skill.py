"""Volume skill: control system audio volume via pactl or amixer."""
from __future__ import annotations

import re
import shutil
import subprocess

from skills.base import Skill


def _find_backend() -> str | None:
    for cmd in ["pactl", "amixer"]:
        if shutil.which(cmd):
            return cmd
    return None


class VolumeSkill(Skill):
    name = "volume"

    def __init__(self) -> None:
        self._backend = _find_backend()

    def can_handle(self, text: str) -> bool:
        t = text.lower()
        if "volume" in t:
            return True
        if any(k in t for k in ["muta o som", "mutar", "desmuta", "silenciar o som", "sem som", "desmutar"]):
            return True
        if any(k in t for k in ["som mais alto", "som mais baixo", "aumenta o som", "diminui o som"]):
            return True
        return False

    def handle(self, text: str) -> str:
        if not self._backend:
            return "Controle de volume nao disponivel neste sistema."
        t = text.lower()

        if any(k in t for k in ["muta", "silenciar", "sem som", "mute"]):
            return self._set_mute(True)
        if any(k in t for k in ["desmuta", "unmute", "liga o som", "restaura o som"]):
            return self._set_mute(False)

        m = re.search(r"\b(\d{1,3})\s*%", t)
        if m:
            pct = max(0, min(100, int(m.group(1))))
            return self._set_volume(pct)

        if any(k in t for k in ["aumenta", "sobe", "mais alto", "mais volume", "aumentar"]):
            step = self._extract_step(t)
            return self._change_volume(f"+{step}%")
        if any(k in t for k in ["diminui", "baixa", "menos volume", "mais baixo", "diminuir"]):
            step = self._extract_step(t)
            return self._change_volume(f"-{step}%")

        return "Nao entendi o comando de volume. Tente: 'volume 50%', 'aumenta o volume' ou 'muta o som'."

    def _set_volume(self, pct: int) -> str:
        if self._backend == "pactl":
            self._run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{pct}%"])
        else:
            self._run(["amixer", "set", "Master", f"{pct}%"])
        return f"Volume ajustado para {pct}%."

    def _change_volume(self, delta: str) -> str:
        if self._backend == "pactl":
            self._run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", delta])
        else:
            sign = delta[0]
            val = delta[1:]
            self._run(["amixer", "set", "Master", f"{val}{sign}"])
        direction = "aumentado" if delta.startswith("+") else "diminuido"
        return f"Volume {direction}."

    def _set_mute(self, mute: bool) -> str:
        if self._backend == "pactl":
            self._run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if mute else "0"])
        else:
            self._run(["amixer", "set", "Master", "mute" if mute else "unmute"])
        return "Som silenciado." if mute else "Som restaurado."

    @staticmethod
    def _extract_step(text: str, default: int = 10) -> int:
        m = re.search(r"\b(\d+)\b", text)
        return int(m.group(1)) if m else default

    @staticmethod
    def _run(cmd: list[str]) -> None:
        try:
            subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            pass
