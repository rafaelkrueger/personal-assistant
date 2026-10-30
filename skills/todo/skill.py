from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from skills import spoken
from skills.base import Skill


class TodoSkill(Skill):
    name = "todo"

    def __init__(self, db_path: str = "data/todos.json") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.db_path.exists():
            self._save([])

    def can_handle(self, text: str) -> bool:
        lowered = text.lower()
        return "lista de tarefas" in lowered or (
            "taref" in lowered and any(k in lowered for k in ["adicion", "remov", "listar", "conclu", "marcar"])
        )

    def handle(self, text: str) -> str:
        lowered = spoken.norm(text)
        if any(k in lowered for k in ["listar", "mostrar", "mostra", "quais", "ver tarefas", "o que tem",
                                      "ler a lista", "le a lista", "minhas tarefas"]):
            return self._list_tasks_text()
        # o verbo é a palavra inteira: "Adicionar pagar luz" é "pagar luz" (antes entrava "ar pagar luz")
        action = spoken.first_action(text, {"remove": spoken.REMOVE_VERBS, "done": spoken.DONE_VERBS,
                                            "add": spoken.ADD_VERBS})
        if action == "remove":
            title = self._title(text, spoken.REMOVE_VERBS)
            if not title:
                return "Qual tarefa voce quer remover?"
            if self.remove_task_by_title(title):
                return f"Tarefa removida: {title}."
            return f"Nao encontrei a tarefa '{title}'."
        if action == "done":
            title = self._title(text, spoken.DONE_VERBS)
            if not title:
                return "Qual tarefa voce quer marcar como concluida?"
            if self.mark_done_by_title(title):
                return f"Tarefa marcada como concluida: {title}."
            return f"Nao encontrei a tarefa '{title}'."
        if action == "add":
            title = self._title(text, spoken.ADD_VERBS)
            if not title:
                return "Qual tarefa voce quer adicionar?"
            self.add_task(title)
            return f"Tarefa adicionada: {title}."
        return "Posso adicionar, remover, concluir ou listar sua lista de tarefas."

    def list_tasks(self) -> list[dict]:
        return self._load()

    def add_task(self, title: str) -> dict:
        tasks = self._load()
        task = {
            "id": uuid4().hex[:10],
            "title": title.strip(),
            "completed": False,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        tasks.append(task)
        self._save(tasks)
        return task

    def remove_task(self, task_id: str) -> bool:
        tasks = self._load()
        new_tasks = [t for t in tasks if t.get("id") != task_id]
        changed = len(new_tasks) != len(tasks)
        if changed:
            self._save(new_tasks)
        return changed

    def set_task_completed(self, task_id: str, completed: bool) -> bool:
        tasks = self._load()
        changed = False
        for task in tasks:
            if task.get("id") == task_id:
                task["completed"] = completed
                changed = True
                break
        if changed:
            self._save(tasks)
        return changed

    def mark_done_by_title(self, title: str) -> bool:
        norm = spoken.norm(title)  # sem acento nem maiúscula: o falado acha o digitado
        tasks = self._load()
        for task in tasks:
            if spoken.norm(str(task.get("title", ""))) == norm:
                task["completed"] = True
                self._save(tasks)
                return True
        return False

    def remove_task_by_title(self, title: str) -> bool:
        norm = spoken.norm(title)
        tasks = self._load()
        for task in tasks:
            if spoken.norm(str(task.get("title", ""))) == norm:
                return self.remove_task(str(task.get("id")))
        return False

    def _list_tasks_text(self) -> str:
        tasks = self._load()
        if not tasks:
            return "Sua lista de tarefas esta vazia."
        lines = ["Lista de tarefas:"]
        for idx, task in enumerate(tasks, start=1):
            marker = "x" if task.get("completed") else " "
            lines.append(f"{idx}. [{marker}] {task.get('title', 'tarefa')}")
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
    def _title(text: str, verbs: str) -> str:
        """A tarefa depois do verbo, sem "na lista de tarefas" nem "como concluída"."""
        found = spoken.item_after_verb(text, verbs)
        title = found[0] if found else ""
        return re.sub(r"\s+(?:como\s+)?(?:conclu[ií]d[ao]|feit[ao]|finalizad[ao])$", "", title, flags=re.IGNORECASE)
