from __future__ import annotations

import re

from cassandra.alarm_manager import AlarmManager
from skills.base import Skill

_DAY_MAP = {
    "segunda": 0, "seg": 0,
    "terça": 1, "terca": 1, "ter": 1,
    "quarta": 2, "qua": 2,
    "quinta": 3, "qui": 3,
    "sexta": 4, "sex": 4,
    "sábado": 5, "sabado": 5, "sab": 5,
    "domingo": 6, "dom": 6,
}


class AlarmSkill(Skill):
    name = "alarm"

    def __init__(self, alarm_manager: AlarmManager) -> None:
        self.alarm_manager = alarm_manager

    def can_handle(self, text: str) -> bool:
        lowered = text.lower()
        return any(k in lowered for k in ["alarme", "acorde", "despert", "parar alarme", "para alarme"])

    def handle(self, text: str) -> str:
        lowered = text.lower()

        if any(k in lowered for k in ["parar alarme", "para alarme", "desligar alarme", "parar o alarme"]):
            if self.alarm_manager.stop_ringing():
                return "Alarme parado."
            return "Nao ha alarme tocando agora."

        if any(k in lowered for k in ["listar alarmes", "quais alarmes", "mostrar alarmes"]):
            alarms = self.alarm_manager.list_alarms()
            if not alarms:
                return "Voce nao tem alarmes cadastrados."
            lines = ["Seus alarmes:"]
            for idx, alarm in enumerate(alarms, start=1):
                days = alarm.get("days_of_week")
                if days:
                    day_names = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"]
                    day_str = ", ".join(day_names[d] for d in days)
                elif alarm["recurring_daily"]:
                    day_str = "todos os dias"
                else:
                    day_str = "uma vez"
                status = "ativo" if alarm["enabled"] else "desativado"
                lines.append(f"{idx}. {alarm['time_hhmm']} ({day_str}, {status})")
            return "\n".join(lines)

        when = self._extract_time(text)
        if not when:
            return "Nao entendi o horario. Exemplo: 'alarme as 7' ou 'alarme as 6:30 de segunda a sexta'."

        days_of_week, recurring = self._extract_days(lowered)
        alarm = self.alarm_manager.add_alarm(
            when, recurring_daily=recurring, days_of_week=days_of_week, label="Alarme Cassandra"
        )

        if days_of_week:
            day_names = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"]
            day_str = ", ".join(day_names[d] for d in days_of_week)
            recur_text = f"toda(s) {day_str}"
        elif recurring:
            recur_text = "todos os dias"
        else:
            recur_text = "uma vez"

        return f"Alarme criado para {alarm.time_hhmm} ({recur_text})."

    @staticmethod
    def _extract_time(text: str) -> str | None:
        m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\b", text)
        if not m:
            return None
        hour = int(m.group(1))
        minute = int(m.group(2) or "00")
        if hour > 23 or minute > 59:
            return None
        return f"{hour:02d}:{minute:02d}"

    @staticmethod
    def _extract_days(text: str) -> tuple[list[int] | None, bool]:
        """Returns (days_of_week, recurring_daily)."""
        # Preset: weekdays
        if any(k in text for k in ["dias úteis", "dias uteis", "dia util", "dias da semana"]):
            return [0, 1, 2, 3, 4], True

        # Preset: weekends
        if any(k in text for k in ["fins de semana", "fim de semana", "final de semana"]):
            return [5, 6], True

        # Every day
        if any(k in text for k in ["todos os dias", "todo dia", "diariamente", "todo dia"]):
            return None, True

        # Specific day names
        days: set[int] = set()
        for word, num in _DAY_MAP.items():
            if re.search(rf"\b{re.escape(word)}\b", text):
                days.add(num)
        if days:
            return sorted(days), True

        # No recurrence keywords → one-time
        return None, False
