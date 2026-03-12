from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from skills.base import Skill


@dataclass
class ScheduleItem:
    title: str
    when: str


class ScheduleSkill(Skill):
    name = "schedule"

    def __init__(self, db_path: str = "data/agenda.json") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.db_path.exists():
            self._save([])

    def can_handle(self, text: str) -> bool:
        lowered = text.lower()
        keywords = ["agenda", "compromisso", "marcar", "agendar", "lembrete"]
        return any(word in lowered for word in keywords)

    def handle(self, text: str) -> str:
        lowered = text.lower()
        if any(word in lowered for word in ["listar", "mostrar", "ver agenda", "minha agenda"]):
            return self._list_items()

        if any(word in lowered for word in ["marcar", "agendar", "novo compromisso"]):
            return self._create_item(text)

        return (
            "Para agenda, voce pode pedir: 'cassandra, marcar compromisso Reuniao amanha 14:00' "
            "ou 'cassandra, mostrar agenda'."
        )

    def _create_item(self, text: str) -> str:
        cleaned = text.strip()
        marker = "compromisso"
        idx = cleaned.lower().find(marker)
        if idx == -1:
            marker = "agendar"
            idx = cleaned.lower().find(marker)

        payload = cleaned[idx + len(marker) :].strip() if idx != -1 else ""
        if not payload:
            return "Me diga o compromisso. Exemplo: marcar compromisso Dentista 15/03 09:30."

        item = ScheduleItem(title=payload, when=datetime.now().isoformat())
        data = self._load()
        data.append(item.__dict__)
        self._save(data)
        return f"Compromisso registrado: {payload}"

    def _list_items(self) -> str:
        data = self._load()
        if not data:
            return "Sua agenda esta vazia."

        lines = ["Seus compromissos:"]
        for index, item in enumerate(data, start=1):
            lines.append(f"{index}. {item.get('title', 'Sem titulo')}")
        return "\n".join(lines)

    def _load(self) -> list[dict]:
        try:
            return json.loads(self.db_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

    def _save(self, data: list[dict]) -> None:
        self.db_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
