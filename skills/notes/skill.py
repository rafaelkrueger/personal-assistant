"""Notes skill: save, list, and delete quick voice notes."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from skills.base import Skill

_DB = Path("data/notes.json")
_TRIGGER_SAVE = ["anota", "cria nota", "nova nota", "adiciona nota", "anote"]
_TRIGGER_LIST = ["minhas notas", "listar notas", "lista as notas", "ver notas", "quais notas"]
_TRIGGER_DEL  = ["apaga nota", "deleta nota", "remove nota", "deletar nota", "apagar nota"]


class NotesSkill(Skill):
    name = "notes"

    def can_handle(self, text: str) -> bool:
        t = text.lower()
        return any(k in t for k in _TRIGGER_SAVE + _TRIGGER_LIST + _TRIGGER_DEL)

    def handle(self, text: str) -> str:
        t = text.lower()
        if any(k in t for k in _TRIGGER_LIST):
            return self._list()
        if any(k in t for k in _TRIGGER_DEL):
            return self._delete(text)
        return self._save(text)

    # --- public CRUD for web API ---
    def list_items(self) -> list[dict]:
        return self._load()

    def add_item(self, content: str) -> dict:
        note = {
            "id": uuid4().hex[:8],
            "content": content.strip(),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        notes = self._load()
        notes.append(note)
        self._persist(notes)
        return note

    def remove_item(self, note_id: str) -> bool:
        notes = self._load()
        new = [n for n in notes if n["id"] != note_id]
        if len(new) == len(notes):
            return False
        self._persist(new)
        return True

    # --- internal ---
    def _save(self, text: str) -> str:
        content = text
        for kw in sorted(_TRIGGER_SAVE, key=len, reverse=True):
            content = re.sub(rf"(?i)\b{re.escape(kw)}\b[\s:,]*(que\s+)?", "", content).strip()
        if not content:
            return "Nao entendi o que anotar. Diga: 'anota que preciso ligar pro medico'."
        note = self.add_item(content)
        return f"Anotado: {note['content']}"

    def _list(self) -> str:
        notes = self._load()
        if not notes:
            return "Voce nao tem nenhuma nota salva."
        lines = [f"Suas {len(notes)} nota(s):"]
        for i, n in enumerate(notes, 1):
            lines.append(f"{i}. {n['content']}")
        return "\n".join(lines)

    def _delete(self, text: str) -> str:
        m = re.search(r"\b(\d+)\b", text)
        if not m:
            return "Qual nota quer apagar? Diga o numero. Ex: 'apaga nota 2'."
        idx = int(m.group(1)) - 1
        notes = self._load()
        if idx < 0 or idx >= len(notes):
            return f"Nota {idx + 1} nao existe. Voce tem {len(notes)} nota(s)."
        deleted = notes.pop(idx)
        self._persist(notes)
        return f"Nota apagada: {deleted['content']}"

    def _load(self) -> list[dict]:
        _DB.parent.mkdir(parents=True, exist_ok=True)
        if not _DB.exists():
            return []
        try:
            data = json.loads(_DB.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _persist(self, notes: list[dict]) -> None:
        _DB.parent.mkdir(parents=True, exist_ok=True)
        _DB.write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
