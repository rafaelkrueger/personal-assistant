from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from cassandra.config import load_settings
from cassandra.memory import ConversationMemory
from cassandra.openai_client import LLMService
from cassandra.router import SkillRouter
from cassandra.timer_manager import TimerManager, format_duration
from skills.general_chat.skill import GeneralChatSkill
from skills.schedule.skill import ScheduleSkill
from skills.timer.skill import TimerSkill
from skills.weather.skill import WeatherSkill


@dataclass
class ChatTurn:
    role: str
    content: str
    timestamp: str
    kind: str = "chat"


class ChatEngine:
    """Text chat engine with persistent per-session memory."""

    def __init__(self, history_path: str = "data/web_chat_history.json") -> None:
        self.settings = load_settings()
        self.llm = LLMService(
            api_key=self.settings.openai_api_key,
            model=self.settings.openai_model,
        )
        self._timer_interrupt = threading.Event()
        self.timer_manager = TimerManager(on_fire=self._timer_interrupt)
        self._sessions: dict[str, ConversationMemory] = {}
        self._history_by_session: dict[str, list[ChatTurn]] = {}
        self._lock = threading.Lock()
        self.history_path = Path(history_path)
        self.history_path.parent.mkdir(parents=True, exist_ok=True)

        self.router = SkillRouter(
            skills=[
                ScheduleSkill(),
                WeatherSkill(),
                TimerSkill(self.timer_manager),
                GeneralChatSkill(self.llm, ConversationMemory()),
            ]
        )
        self._load_history()

    def create_session(self) -> str:
        with self._lock:
            session_id = uuid4().hex
            self._sessions[session_id] = ConversationMemory()
            self._history_by_session[session_id] = []
            self._persist_history()
            return session_id

    def get_history(self, session_id: str) -> list[dict[str, str]]:
        memory = self._ensure_session(session_id)
        _ = memory  # explicit: ensures session exists
        with self._lock:
            turns = self._history_by_session.get(session_id, [])
            return [
                {
                    "role": turn.role,
                    "content": turn.content,
                    "timestamp": turn.timestamp,
                    "kind": turn.kind,
                }
                for turn in turns
            ]

    def chat(self, session_id: str, message: str) -> dict:
        text = (message or "").strip()
        if not text:
            raise ValueError("Message cannot be empty.")

        memory = self._ensure_session(session_id)
        notifications = self._collect_timer_notifications()

        skill = self._build_session_router(memory).route(text)
        if hasattr(skill, "handle_stream"):
            response = "".join(skill.handle_stream(text))
        else:
            response = skill.handle(text)

        memory.add_user(text)
        memory.add_assistant(response)

        timestamp = self._now()
        with self._lock:
            history = self._history_by_session.setdefault(session_id, [])
            history.append(ChatTurn(role="user", content=text, timestamp=timestamp))
            for note in notifications:
                history.append(
                    ChatTurn(
                        role="assistant",
                        content=note,
                        timestamp=timestamp,
                        kind="timer",
                    )
                )
            history.append(ChatTurn(role="assistant", content=response, timestamp=timestamp))
            self._persist_history()

        return {
            "session_id": session_id,
            "reply": response,
            "notifications": notifications,
            "history": self.get_history(session_id),
        }

    def _build_session_router(self, memory: ConversationMemory) -> SkillRouter:
        return SkillRouter(
            skills=[
                ScheduleSkill(),
                WeatherSkill(),
                TimerSkill(self.timer_manager),
                GeneralChatSkill(self.llm, memory),
            ]
        )

    def _ensure_session(self, session_id: str) -> ConversationMemory:
        sid = (session_id or "").strip()
        if not sid:
            raise ValueError("session_id is required.")

        with self._lock:
            memory = self._sessions.get(sid)
            if memory is not None:
                return memory

            memory = ConversationMemory()
            turns = self._history_by_session.get(sid, [])
            for turn in turns:
                if turn.role == "user":
                    memory.add_user(turn.content)
                elif turn.role == "assistant" and turn.kind == "chat":
                    memory.add_assistant(turn.content)
            self._sessions[sid] = memory
            self._history_by_session.setdefault(sid, [])
            return memory

    def _collect_timer_notifications(self) -> list[str]:
        fired = self.timer_manager.pop_fired()
        if not fired:
            return []
        notes = []
        for item in fired:
            label = format_duration(item.duration_seconds)
            notes.append(f"[TIMER] {label} finalizado!")
        return notes

    def _load_history(self) -> None:
        if not self.history_path.exists():
            return
        try:
            raw = json.loads(self.history_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return

        sessions = raw.get("sessions", {})
        if not isinstance(sessions, dict):
            return

        with self._lock:
            for session_id, entries in sessions.items():
                if not isinstance(entries, list):
                    continue
                turns: list[ChatTurn] = []
                for row in entries:
                    if not isinstance(row, dict):
                        continue
                    role = str(row.get("role", "")).strip()
                    content = str(row.get("content", "")).strip()
                    timestamp = str(row.get("timestamp", "")).strip() or self._now()
                    kind = str(row.get("kind", "chat")).strip() or "chat"
                    if role not in {"user", "assistant"} or not content:
                        continue
                    turns.append(
                        ChatTurn(
                            role=role,
                            content=content,
                            timestamp=timestamp,
                            kind=kind,
                        )
                    )
                self._history_by_session[session_id] = turns

    def _persist_history(self) -> None:
        payload = {
            "sessions": {
                session_id: [
                    {
                        "role": turn.role,
                        "content": turn.content,
                        "timestamp": turn.timestamp,
                        "kind": turn.kind,
                    }
                    for turn in turns
                ]
                for session_id, turns in self._history_by_session.items()
            }
        }
        self.history_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
