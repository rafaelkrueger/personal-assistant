"""Hora e data na hora, sem LLM nem internet: "que horas são?", "que dia é hoje?", "que data é hoje?"."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from skills.base import Skill

_WEEKDAYS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
_MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
           "novembro", "dezembro"]
_TIME = re.compile(r"\b(que horas|quantas horas|horas sao|hora e agora|que hora e|me diz a hora|qual a hora|horario agora)\b")
_DATE = re.compile(r"\b(que dia e hoje|que dia hoje|qual o dia de hoje|que data e hoje|qual a data|data de hoje|"
                   r"dia da semana|hoje e que dia)\b")


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _spoken_time(now: datetime) -> str:
    h, m = now.hour, now.minute
    hours = "meia-noite" if h == 0 else ("meio-dia" if h == 12 else f"{h % 12 or 12}")
    period = "" if h in (0, 12) else (" da manhã" if h < 12 else (" da tarde" if h < 18 else " da noite"))
    if h in (0, 12):
        return hours if m == 0 else f"{hours} e {m}"
    plural = "hora" if h % 12 == 1 else "horas"
    return f"{hours} {plural}{period}" if m == 0 else f"{hours} e {m}{period}"


class ClockSkill(Skill):
    name = "clock"

    def can_handle(self, text: str) -> bool:
        t = _norm(text)
        return bool(_TIME.search(t) or _DATE.search(t))

    def handle(self, text: str) -> str:
        now = datetime.now()
        t = _norm(text)
        date = f"{_WEEKDAYS[now.weekday()]}, {now.day} de {_MONTHS[now.month - 1]}"
        if _TIME.search(t) and _DATE.search(t):
            return f"Hoje é {date}, e são {_spoken_time(now)}."
        if _TIME.search(t):
            return f"São {_spoken_time(now)}."
        return f"Hoje é {date} de {now.year}."
