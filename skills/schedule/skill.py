"""Skill de agenda: lê, cria e deleta eventos via CalDAV (Google, iCloud, etc.)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from cassandra.calendar_service import CalendarService
from cassandra.openai_client import LLMService
from skills.base import Skill

_TRIGGER_KEYWORDS = [
    "agenda", "compromisso", "compromissos",
    "reunião", "reuniao", "evento", "eventos",
    "marcar", "agendar", "cancelar compromisso",
    "apagar compromisso", "deletar compromisso",
    "o que tenho", "o que tem", "meus compromissos",
    "minha agenda", "ver agenda",
]

_PARSE_SYSTEM = """Você é um interpretador de comandos de agenda para assistente pessoal.
Analise o comando e responda APENAS com JSON válido (sem markdown), no formato:

Para listar: {"intent":"listar","period":"hoje|amanha|semana|proximos_7_dias"}
Para criar:  {"intent":"criar","title":"...","date":"DD/MM/YYYY","time_start":"HH:MM","time_end":"HH:MM","description":""}
Para deletar: {"intent":"deletar","title":"..."}

Resolva referências relativas ("hoje", "amanhã", "essa sexta") usando a data fornecida.
time_end padrão: 1 hora depois de time_start.
Se não reconhecer o intent, retorne {"intent":"ajuda"}.
Responda SOMENTE com o JSON."""


def _parse_intent(llm: LLMService, text: str, today: str) -> dict:
    raw = llm.client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        max_tokens=150,
        messages=[
            {"role": "system", "content": _PARSE_SYSTEM},
            {"role": "user", "content": f"Data de hoje: {today}\nComando: {text}"},
        ],
    ).choices[0].message.content or "{}"
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    return {"intent": "ajuda"}


def _period_range(period: str) -> tuple[datetime, datetime]:
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    if period == "hoje":
        return today_start, today_end
    if period == "amanha":
        return today_start + timedelta(days=1), today_start + timedelta(days=2)
    # semana / proximos_7_dias
    return today_start, today_start + timedelta(days=7)


class ScheduleSkill(Skill):
    name = "schedule"

    def __init__(self, calendar: CalendarService, llm: LLMService) -> None:
        self._cal = calendar
        self._llm = llm

    def can_handle(self, text: str) -> bool:
        t = text.lower()
        return any(kw in t for kw in _TRIGGER_KEYWORDS)

    def handle(self, text: str) -> str:
        if not self._cal.is_configured():
            return (
                "Sua agenda não está conectada ainda. "
                "Acesse as Configurações no dashboard e conecte seu Google Calendar ou iCloud."
            )

        today = datetime.now().strftime("%d/%m/%Y")
        intent = _parse_intent(self._llm, text, today)
        action = intent.get("intent", "ajuda")

        # ── Listar ────────────────────────────────────────────────────────────
        if action == "listar":
            start, end = _period_range(intent.get("period", "hoje"))
            events = self._cal.list_events(start, end)
            if not events:
                period_str = {"hoje": "hoje", "amanha": "amanhã", "semana": "nos próximos 7 dias"}.get(
                    intent.get("period", "hoje"), "neste período"
                )
                return f"Você não tem compromissos {period_str}."
            lines = [f"Seus compromissos ({intent.get('period','hoje').replace('_',' ')}):"]
            for ev in events:
                lines.append(f"- {ev['start']}: {ev['title']}")
                if ev.get("description"):
                    lines.append(f"  {ev['description'][:80]}")
            return "\n".join(lines)

        # ── Criar ─────────────────────────────────────────────────────────────
        if action == "criar":
            title = intent.get("title", "").strip()
            date_str = intent.get("date", today)
            time_start = intent.get("time_start", "09:00")
            time_end = intent.get("time_end", "10:00")
            if not title:
                return "Não entendi o título do compromisso. Exemplo: 'marcar reunião sexta 14:00'."
            try:
                start_dt = datetime.strptime(f"{date_str} {time_start}", "%d/%m/%Y %H:%M")
                end_dt = datetime.strptime(f"{date_str} {time_end}", "%d/%m/%Y %H:%M")
            except ValueError:
                return "Não consegui interpretar a data ou horário. Tente: 'reunião amanhã às 15:00'."
            result = self._cal.create_event(
                title=title,
                start_dt=start_dt,
                end_dt=end_dt,
                description=intent.get("description", ""),
            )
            if result:
                return f"Compromisso criado: {title} em {result['start']}."
            return "Não consegui criar o compromisso. Verifique a conexão com a agenda."

        # ── Deletar ───────────────────────────────────────────────────────────
        if action == "deletar":
            search_title = (intent.get("title") or "").lower().strip()
            if not search_title:
                return "Qual compromisso você quer cancelar?"
            # Busca nos próximos 30 dias
            now = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            events = self._cal.list_events(now, now + timedelta(days=30))
            match = next(
                (e for e in events if search_title in e["title"].lower()), None
            )
            if not match:
                return f"Não encontrei compromisso com '{search_title}' nos próximos 30 dias."
            ok = self._cal.delete_event(match["id"])
            if ok:
                return f"Compromisso '{match['title']}' cancelado."
            return "Não consegui cancelar o compromisso. Verifique a conexão."

        # ── Ajuda ─────────────────────────────────────────────────────────────
        return (
            "Para agenda você pode dizer: "
            "'quais meus compromissos de hoje', "
            "'marcar reunião amanhã às 14:00', "
            "ou 'cancelar compromisso dentista'."
        )
