"""Skill de voz para gerenciar rotinas da Cassandra."""
from __future__ import annotations

import json
import re

from cassandra.alarm_manager import AlarmManager
from cassandra.openai_client import LLMService
from cassandra.routine_manager import ACTION_LABELS, RoutineManager
from skills.base import Skill

_TRIGGER_KEYWORDS = [
    "rotina", "rotinas", "rotineiro",
    "toda vez que", "todo dia que", "quando o alarme",
    "ao tocar o alarme", "quando tocar",
]

_DAY_NAMES = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

_PARSE_SYSTEM = """Você é um interpretador de rotinas para assistente pessoal.
Analise o comando e responda APENAS com JSON válido (sem markdown).

Formato:
{
  "intent": "criar|remover|listar|executar|ativar|desativar",
  "routine_name": "nome da rotina",
  "trigger": {"type": "alarm|time", "alarm_label": "label do alarme ou horário", "time_hhmm": "HH:MM"},
  "actions": [{"type": "noticias|cotacao|clima|esporte|transito|falar", "text": "só para falar"}]
}

Tipos de ação disponíveis: noticias, cotacao, clima, esporte, transito, falar.
Se não conseguir identificar algum campo, deixe como string vazia.
Responda SOMENTE com o JSON."""


class RoutineSkill(Skill):
    name = "routine"

    def __init__(
        self,
        routine_manager: RoutineManager,
        alarm_manager: AlarmManager,
        llm: LLMService,
    ) -> None:
        self._rm = routine_manager
        self._am = alarm_manager
        self._llm = llm

    def can_handle(self, text: str) -> bool:
        t = text.lower()
        return any(kw in t for kw in _TRIGGER_KEYWORDS)

    def handle(self, text: str) -> str:
        alarms = self._am.list_alarms()
        alarm_list_str = "\n".join(
            f"  id={a['id']} label={a['label']} horário={a['time_hhmm']}"
            for a in alarms
        ) or "  (nenhum alarme cadastrado)"

        raw = self._llm.client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0,
            max_tokens=300,
            messages=[
                {
                    "role": "system",
                    "content": (
                        _PARSE_SYSTEM
                        + f"\n\nAlarmes existentes:\n{alarm_list_str}"
                    ),
                },
                {"role": "user", "content": text},
            ],
        ).choices[0].message.content or "{}"

        m = re.search(r"\{.*\}", raw, re.DOTALL)
        parsed: dict = {}
        if m:
            try:
                parsed = json.loads(m.group())
            except Exception:
                pass

        intent = parsed.get("intent", "listar")

        # ── Listar ────────────────────────────────────────────────────────────
        if intent == "listar":
            routines = self._rm.list_routines()
            if not routines:
                return "Você não tem rotinas cadastradas ainda."
            lines = ["Suas rotinas:"]
            for r in routines:
                status = "ativa" if r["enabled"] else "desativada"
                trig = r["trigger"]
                if trig["type"] == "alarm":
                    alarm = next((a for a in alarms if a["id"] == trig["alarm_id"]), None)
                    trig_str = f"alarme {alarm['label'] if alarm else trig['alarm_id']}"
                else:
                    trig_str = f"às {trig['time_hhmm']}"
                acts = ", ".join(ACTION_LABELS.get(a["type"], a["type"]) for a in r["actions"])
                lines.append(f"- {r['name']} ({trig_str}, {status}): {acts}")
            return "\n".join(lines)

        # ── Criar ─────────────────────────────────────────────────────────────
        if intent == "criar":
            trigger_data = parsed.get("trigger", {})
            actions_data = parsed.get("actions", [])
            name = parsed.get("routine_name") or "Nova rotina"

            if not actions_data:
                return "Não entendi quais ações a rotina deve executar."

            trig_type = trigger_data.get("type", "time")
            trigger = {"type": trig_type}

            if trig_type == "alarm":
                alarm_label = (trigger_data.get("alarm_label") or "").lower()
                matched = next(
                    (a for a in alarms if alarm_label in a["label"].lower()
                     or alarm_label in a["time_hhmm"]),
                    alarms[0] if alarms else None,
                )
                if not matched:
                    return "Não encontrei o alarme mencionado. Crie um alarme primeiro."
                trigger["alarm_id"] = matched["id"]
            else:
                trigger["time_hhmm"] = trigger_data.get("time_hhmm", "07:00")

            routine = self._rm.add_routine(name, trigger, actions_data)
            acts_str = ", ".join(
                ACTION_LABELS.get(a["type"], a["type"]) for a in actions_data
            )
            if trig_type == "alarm":
                alarm = next((a for a in alarms if a["id"] == trigger.get("alarm_id")), None)
                trig_str = f"quando o alarme '{alarm['label'] if alarm else ''}' tocar"
            else:
                trig_str = f"todo dia às {trigger['time_hhmm']}"
            return f"Rotina '{routine.name}' criada: {trig_str}, executará: {acts_str}."

        # ── Remover ───────────────────────────────────────────────────────────
        if intent == "remover":
            name = (parsed.get("routine_name") or "").lower()
            routines = self._rm.list_routines()
            target = next((r for r in routines if name in r["name"].lower()), None)
            if not target:
                return f"Não encontrei rotina com o nome '{name}'."
            self._rm.remove_routine(target["id"])
            return f"Rotina '{target['name']}' removida."

        # ── Executar ──────────────────────────────────────────────────────────
        if intent == "executar":
            name = (parsed.get("routine_name") or "").lower()
            routines = self._rm.list_routines()
            target = next((r for r in routines if name in r["name"].lower()), None)
            if not target:
                return "Não encontrei essa rotina para executar."
            self._rm.run_routine(target["id"])
            return f"Executando a rotina '{target['name']}' agora."

        # ── Ativar / Desativar ────────────────────────────────────────────────
        if intent in ("ativar", "desativar"):
            name = (parsed.get("routine_name") or "").lower()
            routines = self._rm.list_routines()
            target = next((r for r in routines if name in r["name"].lower()), None)
            if not target:
                return f"Não encontrei rotina '{name}'."
            enabled = intent == "ativar"
            self._rm.toggle_routine(target["id"], enabled)
            return f"Rotina '{target['name']}' {'ativada' if enabled else 'desativada'}."

        return "Não entendi o que você quer fazer com as rotinas."
