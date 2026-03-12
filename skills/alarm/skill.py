from __future__ import annotations

import re

from cassandra.alarm_manager import AlarmManager
from skills.base import Skill


class AlarmSkill(Skill):
    name = "alarm"

    def __init__(self, alarm_manager: AlarmManager) -> None:
        self.alarm_manager = alarm_manager

    def can_handle(self, text: str) -> bool:
        lowered = text.lower()
        keywords = ["alarme", "acorde", "despert", "parar alarme", "para alarme"]
        return any(k in lowered for k in keywords)

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
                recur = "todos os dias" if alarm["recurring_daily"] else "uma vez"
                status = "ativo" if alarm["enabled"] else "desativado"
                lines.append(f"{idx}. {alarm['time_hhmm']} ({recur}, {status})")
            return "\n".join(lines)

        when = self._extract_time(text)
        if not when:
            return (
                "Nao entendi o horario. Exemplo: 'alarme as 7' ou "
                "'alarme todos os dias as 6:30'."
            )
        recurring = any(k in lowered for k in ["todos os dias", "todo dia", "diariamente"])
        alarm = self.alarm_manager.add_alarm(when, recurring_daily=recurring, label="Alarme Cassandra")
        recur_text = "todos os dias" if recurring else "uma vez"
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
