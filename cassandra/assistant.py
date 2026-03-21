from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from cassandra.config import load_settings
from cassandra.input_sources import InputEvent, MicrophoneInputSource, TextInputSource
from cassandra.memory import ConversationMemory
from cassandra.openai_client import LLMService
from cassandra.router import SkillRouter
from cassandra.settings_store import SettingsStore
from cassandra.sounds import SoundPlayer
from cassandra.speaker_keepalive import SpeakerKeepAlive
from cassandra.timer_manager import TimerManager, format_duration
from cassandra.voice import VoiceOutput
from cassandra.alarm_manager import AlarmManager
from skills.alarm.skill import AlarmSkill
from skills.general_chat.skill import GeneralChatSkill
from skills.schedule.skill import ScheduleSkill
from skills.shopping_list.skill import ShoppingListSkill
from skills.timer.skill import TimerSkill
from skills.todo.skill import TodoSkill
from skills.routine.skill import RoutineSkill
from skills.volume.skill import VolumeSkill
from skills.web_search.skill import WebSearchSkill
from cassandra.routine_manager import RoutineManager
from cassandra.calendar_service import CalendarService


class CassandraAssistant:
    def __init__(self) -> None:
        self.settings = load_settings()
        self.settings_store = SettingsStore()
        self.llm = LLMService(
            api_key=self.settings.openai_api_key,
            model=self.settings.openai_model,
        )
        self.memory = ConversationMemory()
        self.sound_player = SoundPlayer()
        _ui_sounds = self.settings_store.get().get("sounds", {})
        self.sound_player.enabled = bool(_ui_sounds.get("enabled", True))
        self.sound_player.play(self.settings.startup_sound_path)
        self._timer_interrupt = threading.Event()
        self.timer_manager = TimerManager(on_fire=self._timer_interrupt)
        self.routine_manager = RoutineManager(
            voice_output=None,  # preenchido abaixo após voice_output ser criado
            llm=self.llm,
        )
        self.alarm_manager = AlarmManager(
            ring_sound_path=self.settings.ring_sound_path,
            sound_player=self.sound_player,
            on_alarm_fire=self.routine_manager.on_alarm_fire,
        )
        self.calendar = CalendarService()
        self.shopping_skill = ShoppingListSkill()
        self.todo_skill = TodoSkill()
        self.router = SkillRouter(
            skills=[
                AlarmSkill(self.alarm_manager),
                TimerSkill(self.timer_manager),
                VolumeSkill(),
                ScheduleSkill(self.calendar, self.llm),
                self.shopping_skill,
                self.todo_skill,
                RoutineSkill(self.routine_manager, self.alarm_manager, self.llm),
                WebSearchSkill(self.llm),
                GeneralChatSkill(self.llm, self.memory),
            ]
        )
        if self.settings.input_mode == "mic":
            self.input_source = MicrophoneInputSource(
                llm=self.llm,
                transcription_model=self.settings.transcription_model,
                transcription_language=self.settings.transcription_language,
                transcription_prompt=self.settings.transcription_prompt,
                vad_energy_threshold=self.settings.vad_energy_threshold,
                vad_silence_duration=self.settings.vad_silence_duration,
                vad_wake_silence_duration=self.settings.vad_wake_silence_duration,
                vad_max_duration=self.settings.vad_max_duration,
                interrupt_event=self._timer_interrupt,
                debug=self.settings.mic_debug,
            )
        else:
            self.input_source = TextInputSource()
        self.voice_output = VoiceOutput(
            enabled=self.settings.voice_enabled,
            llm=self.llm,
            tts_voice=self.settings.tts_voice,
            tts_model=self.settings.tts_model,
            fallback_lang=self.settings.voice_lang,
            fallback_rate=self.settings.voice_rate,
        )
        self.routine_manager._voice = self.voice_output  # conecta após criação
        self.speaker_keepalive = SpeakerKeepAlive(interval_seconds=240)
        self.speaker_keepalive.start()
        self.action_log_path = Path("data/action_commands.log")
        self.action_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.passive_log_path = Path("data/passive_heard.log")
        self.conversation_history_path = Path("data/conversation_history.json")
        self._state_lock = threading.Lock()
        self._conversation_history: list[dict[str, str]] = []
        self._web_session_active = False
        self._load_conversation_history()

    def run(self) -> None:
        aliases = self.settings.assistant_aliases or [self.settings.assistant_name]
        print(
            f"Assistente {self.settings.assistant_name} iniciada. "
            f"Diga/digite 'sair' para encerrar."
        )
        print(f"Alias ativos: {', '.join(aliases)} | Modo: {self.settings.input_mode}")
        if self.settings.input_mode == "mic" and self.settings.mic_debug:
            print(
                f"[DEBUG] VAD threshold={self.settings.vad_energy_threshold} | "
                f"wake_silence={self.settings.vad_wake_silence_duration}s | "
                f"cmd_silence={self.settings.vad_silence_duration}s | "
                f"max={self.settings.vad_max_duration}s"
            )

        active_until: float | None = None

        while True:
            self._timer_interrupt.clear()
            # Use a shorter silence threshold when waiting for the wake word.
            in_active_session = active_until is not None
            event = self.input_source.read(wake_phase=not in_active_session)

            # Handle fired timers before anything else
            if self.timer_manager.has_fired():
                for fired in self.timer_manager.pop_fired():
                    label = format_duration(fired.duration_seconds)
                    print(f"Cassandra: [TIMER] {label} finalizado!")
                    self.sound_player.play(self.settings.ring_sound_path)
                    self.sound_player.play(self.settings.ring_sound_path)
                if active_until is not None:
                    active_until = time.monotonic() + self.settings.wake_timeout_seconds
                continue

            if event.exit_requested:
                self._shutdown_with_goodbye()
                break

            now = time.monotonic()
            if active_until is not None and now >= active_until:
                self.sound_player.play(self.settings.off_sound_path)
                active_until = None
                self.memory.clear()
                if self.settings.mic_debug:
                    print("[SESSION] Sessao expirada. Memoria limpa.")

            raw_text = event.text.strip()
            if not raw_text:
                if active_until is not None:
                    retry = "Nao entendi. Pode repetir, por favor?"
                    self.voice_output.speak(retry)
                    print(f"Cassandra: {retry}")
                    self.sound_player.play(self.settings.on_sound_path)
                continue

            if self.settings.mic_debug and self.settings.input_mode == "mic":
                print(f"[ROUTER] Recebido: {raw_text!r}")

            wake_detected, wake_command = self._parse_wake(raw_text)

            if active_until is None and not wake_detected:
                self._log_passive_heard(raw_text)
                if self.settings.mic_debug and self.settings.input_mode == "mic":
                    print("[WAKE] Ignorado: wake word nao detectada.")
                continue

            if wake_detected:
                self.sound_player.play(self.settings.on_sound_path)
                command = wake_command
                command_source = "wake_inline"
                if not command:
                    # Wake word said alone — wait for the follow-up utterance.
                    follow_event = self.input_source.read()
                    if follow_event.exit_requested:
                        self._shutdown_with_goodbye()
                        break
                    command = follow_event.text.strip()
                    command_source = "wake_followup"
                    if not command:
                        retry = "Nao entendi. Pode repetir, por favor?"
                        self.voice_output.speak(retry)
                        print(f"Cassandra: {retry}")
                        self.sound_player.play(self.settings.on_sound_path)
                        active_until = time.monotonic() + self.settings.wake_timeout_seconds
                        continue
            else:
                # Active session: no wake word required.
                command = raw_text
                command_source = "active_session"

            if not command:
                active_until = time.monotonic() + self.settings.wake_timeout_seconds
                continue

            result = self.process_text_command(
                command,
                source=command_source,
                speak_response=True,
            )
            response = result["response"]
            print(f"Cassandra: {response}")
            if result["dismissed"]:
                active_until = None
                continue
            active_until = time.monotonic() + self.settings.wake_timeout_seconds
            # Audible cue that Cassandra is now waiting for the user's next utterance.
            self.sound_player.play(self.settings.on_sound_path)

    def process_text_command(
        self,
        command: str,
        source: str = "text",
        speak_response: bool = False,
    ) -> dict[str, str | bool]:
        text = (command or "").strip()
        if not text:
            raise ValueError("Command cannot be empty.")

        with self._state_lock:
            self._log_action_command(text, source=source)
            self._append_history(role="user", content=text, source=source, kind="chat")

            lowered = text.lower().strip()
            if self.alarm_manager.is_ringing() and lowered in {
                "parar",
                "pare",
                "parar alarme",
                "para alarme",
                "desligar alarme",
            }:
                self.alarm_manager.stop_ringing()
                response = "Alarme parado."
                if speak_response:
                    self.voice_output.speak(response)
                self.memory.add_user(text)
                self.memory.add_assistant(response)
                self._append_history(
                    role="assistant",
                    content=response,
                    source="assistant",
                    kind="chat",
                )
                return {"response": response, "dismissed": False}

            if self._is_dismissal(text):
                goodbye_text = self._dismiss_to_standby(speak_response=speak_response)
                self._append_history(
                    role="assistant",
                    content=goodbye_text,
                    source="assistant",
                    kind="chat",
                )
                return {"response": goodbye_text, "dismissed": True}

            skill = self.router.route(text)
            if hasattr(skill, "handle_stream"):
                stream = skill.handle_stream(text)
                if speak_response:
                    response = self.voice_output.speak_stream(stream)
                else:
                    response = "".join(stream)
            else:
                response = skill.handle(text)
                if speak_response:
                    self.voice_output.speak(response)

            self.memory.add_user(text)
            self.memory.add_assistant(response)
            self._append_history(
                role="assistant",
                content=response,
                source="assistant",
                kind="chat",
            )
            return {"response": response, "dismissed": False}

    def process_web_message(self, message: str) -> dict[str, str | bool]:
        """Handles web messages with wake-word flow similar to voice mode."""
        text = (message or "").strip()
        if not text:
            raise ValueError("Message cannot be empty.")

        with self._state_lock:
            wake_detected, wake_command = self._parse_wake(text)
            if not self._web_session_active and not wake_detected:
                self._log_passive_heard(text)
                wait_msg = (
                    f"Diga '{self.settings.assistant_name}, ...' para me ativar no chat "
                    "antes de enviar comandos."
                )
                self._append_history(
                    role="user",
                    content=text,
                    source="web_passive",
                    kind="passive",
                )
                self._append_history(
                    role="assistant",
                    content=wait_msg,
                    source="assistant",
                    kind="system",
                )
                return {"response": wait_msg, "dismissed": False, "activated": False}

            if wake_detected:
                self.sound_player.play(self.settings.on_sound_path)
                command = (wake_command or "").strip()
                if not command:
                    self._web_session_active = True
                    prompt = "Ativada. Pode mandar o pedido."
                    self._append_history(
                        role="user",
                        content=text,
                        source="web_wake_only",
                        kind="system",
                    )
                    self._append_history(
                        role="assistant",
                        content=prompt,
                        source="assistant",
                        kind="system",
                    )
                    return {"response": prompt, "dismissed": False, "activated": True}
                command_source = "web_wake_inline"
            else:
                command = text
                command_source = "web_active_session"

        result = self.process_text_command(
            command,
            source=command_source,
            speak_response=True,
        )
        with self._state_lock:
            if result["dismissed"]:
                self._web_session_active = False
            else:
                self._web_session_active = True
        return {
            "response": result["response"],
            "dismissed": result["dismissed"],
            "activated": True,
        }

    def get_conversation_history(self) -> list[dict[str, str]]:
        with self._state_lock:
            return [dict(item) for item in self._conversation_history]

    def clear_conversation(self) -> None:
        with self._state_lock:
            self.memory.clear()
            self._conversation_history = []
            self._web_session_active = False
            self._persist_conversation_history()

    def get_shopping_items(self) -> list[dict]:
        return self.shopping_skill.list_items()

    def add_shopping_item(self, name: str) -> dict:
        return self.shopping_skill.add_item(name)

    def remove_shopping_item(self, item_id: str) -> bool:
        return self.shopping_skill.remove_item(item_id)

    def get_todos(self) -> list[dict]:
        return self.todo_skill.list_tasks()

    def add_todo(self, title: str) -> dict:
        return self.todo_skill.add_task(title)

    def remove_todo(self, task_id: str) -> bool:
        return self.todo_skill.remove_task(task_id)

    def set_todo_completed(self, task_id: str, completed: bool) -> bool:
        return self.todo_skill.set_task_completed(task_id, completed)

    # ── Calendar ─────────────────────────────────────────────────────────────

    def get_calendar_status(self) -> dict:
        return self.calendar.get_status()

    def configure_calendar(self, url: str, username: str, password: str) -> dict:
        ok, msg = self.calendar.configure(url, username, password)
        return {"ok": ok, "message": msg}

    def disconnect_calendar(self) -> None:
        self.calendar.disconnect()

    def list_calendar_events(self, days: int = 7) -> list[dict]:
        from datetime import datetime, timedelta
        start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return self.calendar.list_events(start, start + timedelta(days=days))

    def create_calendar_event(
        self, title: str, start_iso: str, end_iso: str, description: str = ""
    ) -> dict | None:
        from datetime import datetime
        try:
            start_dt = datetime.fromisoformat(start_iso)
            end_dt = datetime.fromisoformat(end_iso)
        except ValueError:
            return None
        return self.calendar.create_event(title, start_dt, end_dt, description)

    def delete_calendar_event(self, event_id: str) -> bool:
        return self.calendar.delete_event(event_id)

    # ── Routines ──────────────────────────────────────────────────────────────

    def get_routines(self) -> list[dict]:
        return self.routine_manager.list_routines()

    def add_routine(self, name: str, trigger: dict, actions: list[dict]) -> dict:
        from cassandra.routine_manager import _to_dict
        return _to_dict(self.routine_manager.add_routine(name, trigger, actions))

    def remove_routine(self, routine_id: str) -> bool:
        return self.routine_manager.remove_routine(routine_id)

    def toggle_routine(self, routine_id: str, enabled: bool) -> bool:
        return self.routine_manager.toggle_routine(routine_id, enabled)

    def run_routine(self, routine_id: str) -> bool:
        return self.routine_manager.run_routine(routine_id)

    # ─────────────────────────────────────────────────────────────────────────

    def list_alarms(self) -> list[dict]:
        return self.alarm_manager.list_alarms()

    def add_alarm(
        self,
        time_hhmm: str,
        recurring_daily: bool,
        label: str = "Alarme Cassandra",
        days_of_week: list[int] | None = None,
    ) -> dict:
        alarm = self.alarm_manager.add_alarm(
            time_hhmm=time_hhmm,
            recurring_daily=recurring_daily,
            label=label,
            days_of_week=days_of_week,
        )
        return {
            "id": alarm.id,
            "label": alarm.label,
            "time_hhmm": alarm.time_hhmm,
            "recurring_daily": alarm.recurring_daily,
            "days_of_week": alarm.days_of_week,
            "next_trigger_at": alarm.next_trigger_at,
            "enabled": alarm.enabled,
        }

    def get_ui_settings(self) -> dict:
        s = self.settings_store.get()
        # Augment with read-only runtime info from .env/config
        s["_runtime"] = {
            "assistant_name": self.settings.assistant_name,
            "input_mode": self.settings.input_mode,
            "openai_model": self.settings.openai_model,
            "tts_model_env": self.settings.tts_model,
            "tts_voice_env": self.settings.tts_voice,
        }
        return s

    def save_ui_settings(self, patch: dict) -> dict:
        updated = self.settings_store.update(patch)
        # Apply voice settings dynamically without restart
        v = updated.get("voice", {})
        self.voice_output.enabled = bool(v.get("enabled", True))
        if hasattr(self.voice_output, "tts_voice"):
            self.voice_output.tts_voice = str(v.get("tts_voice", self.settings.tts_voice))
        if hasattr(self.voice_output, "tts_model"):
            self.voice_output.tts_model = str(v.get("tts_model", self.settings.tts_model))
        if hasattr(self.voice_output, "fallback_lang"):
            self.voice_output.fallback_lang = str(v.get("fallback_lang", self.settings.voice_lang))
        if hasattr(self.voice_output, "fallback_rate"):
            self.voice_output.fallback_rate = int(v.get("fallback_rate", self.settings.voice_rate))
        # Apply sounds toggle dynamically
        sounds_on = bool(updated.get("sounds", {}).get("enabled", True))
        self.sound_player.enabled = sounds_on
        return self.get_ui_settings()

    def reset_ui_settings(self) -> dict:
        self.settings_store.reset()
        return self.get_ui_settings()

    def remove_alarm(self, alarm_id: str) -> bool:
        return self.alarm_manager.remove_alarm(alarm_id)

    def stop_alarm_ringing(self) -> bool:
        return self.alarm_manager.stop_ringing()

    def is_alarm_ringing(self) -> bool:
        return self.alarm_manager.is_ringing()

    def _log_action_command(self, command: str, source: str) -> None:
        """Persist recognized post-wake commands for audit/debug."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [{source}] {command}\n"
        try:
            with self.action_log_path.open("a", encoding="utf-8") as fp:
                fp.write(line)
        except OSError:
            # Logging must never break assistant behavior.
            pass
        print(f"[ACTION] {command}")

    def _log_passive_heard(self, text: str) -> None:
        """Persist utterances heard outside active command mode."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [passive_ignored] {text}\n"
        try:
            with self.passive_log_path.open("a", encoding="utf-8") as fp:
                fp.write(line)
        except OSError:
            # Logging must never break assistant behavior.
            pass
        print(f"[PASSIVE] {text}")

    def _append_history(self, role: str, content: str, source: str, kind: str) -> None:
        entry = {
            "role": role,
            "content": content,
            "source": source,
            "kind": kind,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._conversation_history.append(entry)
        self._persist_conversation_history()

    def _load_conversation_history(self) -> None:
        if not self.conversation_history_path.exists():
            return
        try:
            raw = json.loads(self.conversation_history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, list):
            return

        cleaned: list[dict[str, str]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "")).strip()
            content = str(item.get("content", "")).strip()
            source = str(item.get("source", "")).strip() or "unknown"
            kind = str(item.get("kind", "")).strip() or "chat"
            timestamp = str(item.get("timestamp", "")).strip() or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if role not in {"user", "assistant"} or not content:
                continue
            cleaned.append(
                {
                    "role": role,
                    "content": content,
                    "source": source,
                    "kind": kind,
                    "timestamp": timestamp,
                }
            )

        self._conversation_history = cleaned
        for item in cleaned:
            if item["kind"] != "chat":
                continue
            if item["role"] == "user":
                self.memory.add_user(item["content"])
            elif item["role"] == "assistant":
                self.memory.add_assistant(item["content"])

    def _persist_conversation_history(self) -> None:
        try:
            self.conversation_history_path.write_text(
                json.dumps(self._conversation_history, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _shutdown_with_goodbye(self) -> None:
        self.memory.clear()
        goodbye_text = "Ate logo! Encerrando escuta."
        print(f"Cassandra: {goodbye_text}")
        self.voice_output.speak(goodbye_text)
        self.sound_player.play(self.settings.off_sound_path)

    def _dismiss_to_standby(self, speak_response: bool) -> str:
        self.memory.clear()
        standby_text = "Ate logo! Vou ficar em espera. Me chame quando precisar."
        if speak_response:
            self.voice_output.speak(standby_text)
            self.sound_player.play(self.settings.off_sound_path)
        return standby_text

    def _is_dismissal(self, command: str) -> bool:
        """Uses the LLM to classify whether the utterance is a session dismissal.

        Only calls the API for short utterances (up to 12 words); longer
        commands are clearly not goodbyes and skip classification entirely.
        """
        if len(command.split()) > 12:
            return False
        try:
            return self.llm.is_dismissal(command)
        except Exception:
            return False

    def _parse_wake(self, text: str) -> tuple[bool, str | None]:
        aliases = self.settings.assistant_aliases or [self.settings.assistant_name]
        raw = text.strip()

        escaped = [re.escape(alias) for alias in aliases if alias]
        if escaped:
            pattern = rf"^\s*(?:{'|'.join(escaped)})\s*[:,\-]?\s*(.*)$"
            match = re.match(pattern, raw, flags=re.IGNORECASE)
            if match:
                command = match.group(1).strip()
                return True, (command or None)

        first_token = self._normalize_token(raw.lower().split(" ", 1)[0]) if raw else ""
        if not first_token:
            return False, None

        for alias in aliases:
            score = SequenceMatcher(None, first_token, self._normalize_token(alias)).ratio()
            if score >= 0.75:
                remainder = raw.split(" ", 1)[1] if " " in raw else ""
                remainder = remainder.lstrip(" ,:-").strip()
                return True, (remainder or None)

        return False, None

    @staticmethod
    def _normalize_token(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value)
        ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^a-z0-9]", "", ascii_value.lower())
