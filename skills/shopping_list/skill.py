from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from skills.base import Skill


class ShoppingListSkill(Skill):
    name = "shopping_list"

    def __init__(self, db_path: str = "data/shopping_list.json") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.db_path.exists():
            self._save([])

    def can_handle(self, text: str) -> bool:
        lowered = text.lower()
        return "lista de compras" in lowered or (
            "compras" in lowered and any(k in lowered for k in ["adicion", "remov", "listar", "mostrar", "tem"])
        )

    def handle(self, text: str) -> str:
        lowered = text.lower()
        if any(k in lowered for k in ["listar", "mostrar", "o que tem", "tem na lista"]):
            return self._list_items()
        if any(k in lowered for k in ["adicion", "coloque", "incluir"]):
            item = self._extract_item(text, ["adicion", "coloque", "incluir"])
            if not item:
                return "Qual item voce quer adicionar na lista de compras?"
            self.add_item(item)
            return f"Adicionado na lista de compras: {item}."
        if any(k in lowered for k in ["remov", "tirar", "excluir"]):
            item = self._extract_item(text, ["remov", "tirar", "excluir"])
            if not item:
                return "Qual item voce quer remover da lista de compras?"
            if self.remove_item_by_name(item):
                return f"Removido da lista de compras: {item}."
            return f"Nao encontrei '{item}' na lista de compras."
        return "Posso adicionar, remover ou listar sua lista de compras."

    def list_items(self) -> list[dict]:
        return self._load()

    def add_item(self, name: str) -> dict:
        clean = name.strip()
        items = self._load()
        item = {
            "id": uuid4().hex[:10],
            "name": clean,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        items.append(item)
        self._save(items)
        return item

    def remove_item(self, item_id: str) -> bool:
        items = self._load()
        new_items = [i for i in items if i.get("id") != item_id]
        changed = len(new_items) != len(items)
        if changed:
            self._save(new_items)
        return changed

    def remove_item_by_name(self, name: str) -> bool:
        norm = name.strip().lower()
        items = self._load()
        for item in items:
            if str(item.get("name", "")).strip().lower() == norm:
                return self.remove_item(str(item.get("id")))
        return False

    def _list_items(self) -> str:
        items = self._load()
        if not items:
            return "Sua lista de compras esta vazia."
        lines = ["Lista de compras:"]
        for idx, item in enumerate(items, start=1):
            lines.append(f"{idx}. {item.get('name', 'item')}")
        return "\n".join(lines)

    def _load(self) -> list[dict]:
        try:
            raw = json.loads(self.db_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return raw if isinstance(raw, list) else []

    def _save(self, data: list[dict]) -> None:
        self.db_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _extract_item(text: str, markers: list[str]) -> str:
        lowered = text.lower()
        idx = -1
        marker_used = ""
        for marker in markers:
            pos = lowered.find(marker)
            if pos != -1:
                idx = pos
                marker_used = marker
                break
        if idx == -1:
            return ""
        payload = text[idx + len(marker_used) :].strip(" .,:;-")
        payload = payload.replace("na lista de compras", "").replace("da lista de compras", "").strip(" .,:;-")
        return payload
