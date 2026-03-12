from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

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
        lowered = text.lower()
        if any(k in lowered for k in ["listar", "mostrar", "quais", "ver tarefas"]):
            return self._list_tasks_text()
        if any(k in lowered for k in ["adicion", "incluir", "coloque"]):
            title = self._extract_title(text, ["adicion", "incluir", "coloque"])
            if not title:
                return "Qual tarefa voce quer adicionar?"
            self.add_task(title)
            return f"Tarefa adicionada: {title}."
        if any(k in lowered for k in ["conclu", "marcar", "finaliz"]):
            title = self._extract_title(text, ["conclu", "marcar", "finaliz"])
            if not title:
                return "Qual tarefa voce quer marcar como concluida?"
            if self.mark_done_by_title(title):
                return f"Tarefa marcada como concluida: {title}."
            return f"Nao encontrei a tarefa '{title}'."
        if any(k in lowered for k in ["remov", "tirar", "excluir", "apagar"]):
            title = self._extract_title(text, ["remov", "tirar", "excluir", "apagar"])
            if not title:
                return "Qual tarefa voce quer remover?"
            if self.remove_task_by_title(title):
                return f"Tarefa removida: {title}."
            return f"Nao encontrei a tarefa '{title}'."
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
        norm = title.strip().lower()
        tasks = self._load()
        for task in tasks:
            if str(task.get("title", "")).strip().lower() == norm:
                task["completed"] = True
                self._save(tasks)
                return True
        return False

    def remove_task_by_title(self, title: str) -> bool:
        norm = title.strip().lower()
        tasks = self._load()
        for task in tasks:
            if str(task.get("title", "")).strip().lower() == norm:
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
    def _extract_title(text: str, markers: list[str]) -> str:
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
        payload = payload.replace("na lista de tarefas", "").replace("da lista de tarefas", "").strip(" .,:;-")
        return payload
