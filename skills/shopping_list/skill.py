from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from skills import spoken
from skills.base import Skill


class ShoppingListSkill(Skill):
    name = "shopping_list"

    def __init__(self, db_path: str = "data/shopping_list.json") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.db_path.exists():
            self._save([])

    def can_handle(self, text: str) -> bool:
        lowered = spoken.norm(text)
        return bool(re.search(r"\blista (?:de|do|da) (?:compras?|mercado|supermercado|feira)\b", lowered)) or (
            "compras" in lowered and any(k in lowered for k in ["adicion", "remov", "listar", "mostrar", "tem"])
        )

    def handle(self, text: str) -> str:
        lowered = spoken.norm(text)
        if any(k in lowered for k in ["listar", "mostrar", "mostra", "o que tem", "tem na lista", "ler a lista",
                                      "le a lista", "qual e a lista", "como esta a lista"]):
            return self._list_items()
        # o verbo que vem primeiro decide: "tira o leite que eu coloquei" é remover
        action = spoken.first_action(text, {"remove": spoken.REMOVE_VERBS, "add": spoken.ADD_VERBS})
        if action == "remove":
            items = spoken.item_after_verb(text, spoken.REMOVE_VERBS, split=True)
            if not items:
                return "Qual item voce quer remover da lista de compras?"
            gone = [i for i in items if self.remove_item_by_name(i)]
            missing = [i for i in items if i not in gone]
            if gone and not missing:
                return f"Removido da lista de compras: {_join(gone)}."
            if gone:
                return f"Removido da lista de compras: {_join(gone)}. Nao encontrei {_join(missing)}."
            return f"Nao encontrei {_join(missing)} na lista de compras."
        if action == "add":
            items = spoken.item_after_verb(text, spoken.ADD_VERBS, split=True)
            if not items:
                return "Qual item voce quer adicionar na lista de compras?"
            for item in items:
                self.add_item(item)
            return f"Adicionado na lista de compras: {_join(items)}."
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
        norm = spoken.norm(name)  # sem acento nem maiúscula: "Pão" falado acha o "pao" digitado
        items = self._load()
        for item in items:
            if spoken.norm(str(item.get("name", ""))) == norm:
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



def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " e " + items[-1]
