"""Timer skill: set countdown timers that fire in the background."""
from __future__ import annotations

import re

from cassandra.timer_manager import TimerManager, format_duration
from skills import spoken
from skills.alarm.skill import relative
from skills.base import Skill

# Com prazo (ver relative): "me avisa daqui a 10 minutos", "me lembra em meia hora" (texto em spoken.norm).
_TRIGGER_KEYWORDS = [
    "me avisa",
    "me avise",
    "me lembra",
    "me lembre",
    "avisa em",
    "avisa daqui",
    "daqui a",
    "daqui em",
    "dentro de",
]


class TimerSkill(Skill):
    name = "timer"

    def __init__(self, timer_manager: TimerManager) -> None:
        self.tm = timer_manager

    def can_handle(self, text: str) -> bool:
        t = spoken.norm(text)
        if re.search(r"\b(timer|temporizador|cronometro)\b", t):
            return True
        # "me lembra / me avisa" só com prazo ("daqui a 10 minutos", "em meia hora"); num horário ("às 8") é alarme
        return any(kw in t for kw in _TRIGGER_KEYWORDS) and relative(t)

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

    @classmethod
    def _parse_duration(cls, text: str) -> int | None:
        """"5 minutos", "meia hora", "uma hora e meia", "vinte e cinco minutos", "1h30"... (ver skills.spoken).
        Antes "uma hora e meia" virava 1 hora e "1 hora e 30 minutos", 1 hora."""
        return spoken.duration_seconds(text)
