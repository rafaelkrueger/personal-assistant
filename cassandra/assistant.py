from __future__ import annotations

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
from cassandra.sounds import SoundPlayer
from cassandra.timer_manager import TimerManager, format_duration
from cassandra.voice import VoiceOutput
from skills.general_chat.skill import GeneralChatSkill
from skills.schedule.skill import ScheduleSkill
from skills.timer.skill import TimerSkill
from skills.weather.skill import WeatherSkill


class CassandraAssistant:
    def __init__(self) -> None:
        self.settings = load_settings()
        self.llm = LLMService(
            api_key=self.settings.openai_api_key,
            model=self.settings.openai_model,
        )
        self.memory = ConversationMemory()
        self._timer_interrupt = threading.Event()
        self.timer_manager = TimerManager(on_fire=self._timer_interrupt)
        self.router = SkillRouter(
            skills=[
                ScheduleSkill(),
                WeatherSkill(),
                TimerSkill(self.timer_manager),
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
        self.sound_player = SoundPlayer()
        self.voice_output = VoiceOutput(
            enabled=self.settings.voice_enabled,
            llm=self.llm,
            tts_voice=self.settings.tts_voice,
            tts_model=self.settings.tts_model,
            fallback_lang=self.settings.voice_lang,
            fallback_rate=self.settings.voice_rate,
        )
        self.action_log_path = Path("data/action_commands.log")
        self.action_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.passive_log_path = Path("data/passive_heard.log")

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
            else:
                # Active session: no wake word required.
                command = raw_text
                command_source = "active_session"

            if not command:
                active_until = time.monotonic() + self.settings.wake_timeout_seconds
                continue

            self._log_action_command(command, source=command_source)

            if self._is_dismissal(command):
                self._shutdown_with_goodbye()
                break

            skill = self.router.route(command)
            if hasattr(skill, "handle_stream"):
                response = self.voice_output.speak_stream(skill.handle_stream(command))
            else:
                response = skill.handle(command)
                self.voice_output.speak(response)
            self.memory.add_user(command)
            self.memory.add_assistant(response)
            print(f"Cassandra: {response}")
            self.sound_player.play(self.settings.on_sound_path)
            active_until = time.monotonic() + self.settings.wake_timeout_seconds

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

    def _shutdown_with_goodbye(self) -> None:
        self.memory.clear()
        goodbye_text = "Ate logo! Encerrando escuta."
        print(f"Cassandra: {goodbye_text}")
        self.voice_output.speak(goodbye_text)
        self.sound_player.play(self.settings.off_sound_path)

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
