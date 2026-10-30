from __future__ import annotations

import re
from datetime import date, timedelta

from cassandra.alarm_manager import AlarmManager
from skills import spoken
from skills.base import Skill

# Pergunta sobre os alarmes ("tenho algum alarme pra hoje?") lista; antes virava "não entendi o horário".
_ASK = re.compile(r"\b(tenho|tem algum|tem alarme|ha algum|ha alarme|existe|existem|quais|qual e|qual o|quantos|"
                  r"algum alarme|meus alarmes|listar?|mostr\w*)\b")
_CREATE = re.compile(r"\b(coloc\w*|coloqu\w*|cri[ae]\w*|criar|p[oõ]e|ponha|bot[ae]\w*|defin\w*|program\w*|"
                     r"acord[ae]|acordar|despert[ae]|ativ[ae]\w*|adicion\w*|lembr[ae]\w*|avis[ae]\w*)\b")
# Lembrete num horário ("me lembra de tomar o remédio às 8") vira alarme; com prazo ("daqui a 10 minutos") é do timer.
_REMIND = re.compile(r"\b(me lembr\w*|lembr[ae] me|me avis\w*|lembrete)\b")


def relative(t: str) -> bool:
    """O pedido fala de um prazo ("daqui a 10 minutos", "em meia hora"), não de um horário. Texto já em spoken.norm."""
    t = spoken.numbers(t)
    return bool(re.search(r"\bdaqui\s+(?:a|em|uns|umas)\b|\bdentro de\b|"
                          r"\bem\s+(?:\d+|meia|meio)\s*(?:minutos?|segundos?|horas?|mins?|h)\b", t))

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
        t = spoken.norm(text)
        if re.search(r"\b(alarmes?|despertador|despert[ae]|acord[ae]|acordar)\b", t):
            return True
        return bool(_REMIND.search(t)) and not relative(t) and spoken.time_of_day(text) is not None

    def handle(self, text: str) -> str:
        lowered = text.lower()
        t = spoken.norm(text)

        if any(k in lowered for k in ["parar alarme", "para alarme", "desligar alarme", "parar o alarme"]):
            if self.alarm_manager.stop_ringing():
                return "Alarme parado."
            return "Nao ha alarme tocando agora."

        # "Alarme às 7?" (entonação de pergunta) ainda é criar; sem horário, "?" é pergunta sobre os alarmes
        asking = (_ASK.search(t) or ("?" in text and not spoken.time_of_day(text))) and not _CREATE.search(t)
        if asking or any(k in lowered for k in ["listar alarmes", "quais alarmes", "mostrar alarmes"]):
            day = _day(t)
            alarms = [a for a in self.alarm_manager.list_alarms() if day is None or _rings_on(a, day)]
            if not alarms:
                when = {0: " para hoje", 1: " para amanhã", 2: " para depois de amanhã"}.get(
                    (day - date.today()).days if day else -1, "")
                return f"Voce nao tem alarmes{when}." if when else "Voce nao tem alarmes cadastrados."
            lines = ["Seus alarmes:"]
            for idx, alarm in enumerate(alarms, start=1):
                days = alarm.get("days_of_week")
                if alarm.get("date_ymd"):
                    day_str = alarm["date_ymd"]
                elif alarm.get("day_of_month"):
                    day_str = f"todo dia {alarm['day_of_month']}"
                elif days:
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
        label = _reminder_label(text) or "Alarme Cassandra"
        day = None if recurring else _day(t)
        if day is not None and day > date.today():  # "amanhã às 6": não toca hoje às 6
            alarm = self.alarm_manager.add_alarm(when, label=label, date_ymd=day.isoformat())
        else:
            alarm = self.alarm_manager.add_alarm(
                when, recurring_daily=recurring, days_of_week=days_of_week, label=label
            )

        if days_of_week:
            day_names = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"]
            day_str = ", ".join(day_names[d] for d in days_of_week)
            recur_text = f"toda(s) {day_str}"
        elif recurring:
            recur_text = "todos os dias"
        elif day is not None and day > date.today():
            recur_text = "amanhã" if (day - date.today()).days == 1 else day.strftime("%d/%m")
        else:
            recur_text = "uma vez"

        about = f": {label}" if label != "Alarme Cassandra" else ""
        return f"Alarme criado para {alarm.time_hhmm} ({recur_text}){about}."

    @staticmethod
    def _extract_time(text: str) -> str | None:
        """Horário falado: "às 7", "7h30", "sete e meia", "duas da tarde", "dez para as oito" (ver skills.spoken)."""
        return spoken.time_of_day(text)

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

        # Intervalo: "de segunda a sexta", "de terça até quinta" (antes virava só segunda e sexta)
        names = "|".join(sorted(map(re.escape, _DAY_MAP), key=len, reverse=True))
        m = re.search(rf"\b(?:de|da)\s+({names})(?:-feira)?\s+(?:a|à|até|ate)\s+({names})\b", text)
        if m:
            first, last = _DAY_MAP[m.group(1)], _DAY_MAP[m.group(2)]
            span = range(first, last + 1) if first <= last else [*range(first, 7), *range(0, last + 1)]
            return sorted(span), True

        # Specific day names
        days: set[int] = set()
        for word, num in _DAY_MAP.items():
            if re.search(rf"\b{re.escape(word)}\b", text):
                days.add(num)
        if days:
            return sorted(days), True

        # No recurrence keywords → one-time
        return None, False


def _day(t: str) -> date | None:
    """"hoje", "amanhã", "depois de amanhã" (texto em spoken.norm)."""
    today = date.today()
    if "depois de amanha" in t:
        return today + timedelta(days=2)
    if re.search(r"\bamanha\b", t):
        return today + timedelta(days=1)
    if re.search(r"\bhoje\b", t):
        return today
    return None


def _rings_on(alarm: dict, day: date) -> bool:
    """O alarme toca nesse dia?"""
    if not alarm.get("enabled", True):
        return False
    if alarm.get("date_ymd"):
        return alarm["date_ymd"] == day.isoformat()
    if alarm.get("day_of_month"):
        return int(alarm["day_of_month"]) == day.day
    if alarm.get("days_of_week"):
        return day.weekday() in alarm["days_of_week"]
    if alarm.get("recurring_daily"):
        return True
    return str(alarm.get("next_trigger_at", ""))[:10] == day.isoformat()


def _reminder_label(text: str) -> str:
    """"me lembra de tomar o remédio às 8" -> "tomar o remédio" (o motivo do alarme)."""
    m = re.search(r"\b(?:me\s+lembr\w*|lembr\w*\s+me|me\s+avis\w*|lembrete)\s+(?:(?:de|que|pra|para)\s+)?(.+)",
                  text, re.IGNORECASE)
    if not m:
        return ""
    hour = r"(?:\d|meio|meia|uma|duas|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez|onze|doze)"
    about = re.split(rf"\s+(?:às|as|pras|pra|para as|ao|à|a)\s+{hour}|\s+(?:hoje|amanhã|amanha|depois de amanhã|"
                     rf"todos? os dias|toda|todo)\b|\s+\d", m.group(1), maxsplit=1, flags=re.IGNORECASE)[0]
    return about.strip(" .,;:!?")
