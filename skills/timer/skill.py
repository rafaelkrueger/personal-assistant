"""Timer skill: set countdown timers that fire in the background."""
from __future__ import annotations

import re

from cassandra.timer_manager import TimerManager, format_duration
from skills.base import Skill

_TRIGGER_KEYWORDS = [
    "timer",
    "cronômetro",
    "cronometro",
    "alarme",
    "me avisa",
    "me lembra",
    "avisa em",
    "avisa daqui",
    "daqui a",
    "daqui em",
]


class TimerSkill(Skill):
    name = "timer"

    def __init__(self, timer_manager: TimerManager) -> None:
        self.tm = timer_manager

    def can_handle(self, text: str) -> bool:
        lowered = text.lower()
        return any(kw in lowered for kw in _TRIGGER_KEYWORDS)

    def handle(self, text: str) -> str:
        lowered = text.lower()

        # Cancel request
        if any(w in lowered for w in ("cancela", "cancele", "canceler", "para o timer", "remove o timer")):
            names = self.tm.active_names()
            if not names:
                return "Não há timers ativos."
            for name in names:
                self.tm.cancel(name)
            return f"Timer{'s' if len(names) > 1 else ''} cancelado{'s' if len(names) > 1 else ''}."

        # List active timers
        if any(w in lowered for w in ("quantos timers", "timers ativos", "tem timer")):
            names = self.tm.active_names()
            if not names:
                return "Não há timers ativos no momento."
            return f"Timers ativos: {', '.join(names)}."

        duration = self._parse_duration(text)
        if duration is None:
            return (
                "Não entendi a duração. Diga por exemplo: "
                "'timer de 5 minutos' ou 'me avisa em 30 segundos'."
            )

        label = format_duration(duration)
        # Use a human-readable name for the timer
        timer_name = f"timer_{duration}s"
        self.tm.add(timer_name, duration)
        return f"Timer de {label} iniciado. Vou te avisar quando terminar."

    _WORD_TO_NUM = {
        "um": 1, "uma": 1, "dois": 2, "duas": 2, "três": 3, "tres": 3,
        "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9,
        "dez": 10, "onze": 11, "doze": 12, "treze": 13, "quatorze": 14,
        "catorze": 14, "quinze": 15, "dezesseis": 16, "dezessete": 17,
        "dezoito": 18, "dezenove": 19, "vinte": 20, "trinta": 30,
        "quarenta": 40, "cinquenta": 50, "sessenta": 60,
    }

    @classmethod
    def _normalize_numbers(cls, text: str) -> str:
        for word, num in cls._WORD_TO_NUM.items():
            text = re.sub(rf"\b{word}\b", str(num), text)
        return text

    @classmethod
    def _parse_duration(cls, text: str) -> int | None:
        t = cls._normalize_numbers(text.lower())

        m = re.search(r"(\d+)\s*(?:hora|horas|hr|hrs|h)\b", t)
        if m:
            return int(m.group(1)) * 3600

        m = re.search(r"(\d+)\s*(?:minuto|minutos|min|mins)\b", t)
        if m:
            return int(m.group(1)) * 60

        m = re.search(r"(\d+)\s*(?:segundo|segundos|seg|segs)\b", t)
        if m:
            return int(m.group(1))

        # Bare number with no unit → assume minutes
        m = re.search(r"\b(\d+)\b", t)
        if m:
            return int(m.group(1)) * 60

        return None
