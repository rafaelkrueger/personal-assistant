"""Volume skill: control system audio volume (wpctl/PipeWire, pactl or amixer — see cassandra/audio_devices.py)."""
from __future__ import annotations

import re

from cassandra import audio_devices
from skills import spoken
from skills.base import Skill


class VolumeSkill(Skill):
    name = "volume"

    def __init__(self) -> None:
        self._backend = audio_devices._backend()

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
        # Como a transcrição devolve: "volume 50", "volume em cinquenta", "no máximo", "aumenta um pouco".
        plain = re.sub(r"\bum pouc\w*", " ", spoken.norm(text))  # "um pouco" não é o número 1
        t = spoken.numbers(plain)

        # "desmuta" antes de "muta" (antes "desmuta o som" silenciava: "muta" está dentro de "desmuta")
        if re.search(r"\b(desmut\w*|unmute|liga o som|restaura o som|volta o som|tira do mudo)\b", t):
            return self._set_mute(False)
        if re.search(r"\b(mut\w*|silenci\w*|sem som|mute)\b", t):
            return self._set_mute(True)

        up = re.search(r"\b(aument\w*|sobe|subir|mais alto|mais volume)\b", t)
        down = re.search(r"\b(diminu\w*|baix\w*|abaix\w*|menos volume|mais baixo)\b", t)
        if re.search(r"\b(maximo|no talo)\b", t) and not down:
            return self._set_volume(100)
        if re.search(r"\bminimo\b", t) and not up:
            return self._set_volume(10)
        if re.search(r"\b(metade|meio volume)\b", t):
            return self._set_volume(50)
        m = re.search(r"\b(\d{1,3})\b", t)
        if up or down:
            step = int(m.group(1)) if m else 10
            return self._change_volume(f"{'+' if up else '-'}{step}%")
        if m:
            return self._set_volume(max(0, min(100, int(m.group(1)))))

        return "Nao entendi o comando de volume. Tente: 'volume 50', 'aumenta o volume' ou 'muta o som'."

    def _set_volume(self, pct: int) -> str:
        audio_devices.set_volume(pct)
        return f"Volume ajustado para {pct}%."

    def _change_volume(self, delta: str) -> str:
        audio_devices.change_volume(int(delta.rstrip("%")))
        direction = "aumentado" if delta.startswith("+") else "diminuido"
        return f"Volume {direction}."

    def _set_mute(self, mute: bool) -> str:
        audio_devices.set_mute(mute)
        return "Som silenciado." if mute else "Som restaurado."
