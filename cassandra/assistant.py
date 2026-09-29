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
from cassandra import speech_state
from cassandra.mic_monitor import monitor as mic_monitor
from cassandra.music_pause import MusicPause
from cassandra import conversation_mode, notices
from cassandra import llm_settings
from cassandra.openai_client import LLMService
from cassandra.router import SkillRouter
from cassandra.settings_store import SettingsStore
from cassandra.sounds import SoundPlayer
from cassandra.speaker_keepalive import SpeakerKeepAlive
from cassandra.timer_manager import TimerManager, format_duration
from cassandra.voice import VoiceOutput
from cassandra.alarm_manager import AlarmManager
from skills.alarm.skill import AlarmSkill
from skills.clock.skill import ClockSkill
from skills.general_chat.skill import GeneralChatSkill
from skills.schedule.skill import ScheduleSkill
from skills.shopping_list.skill import ShoppingListSkill
from skills.spotify.skill import SpotifySkill
from skills.tv.skill import TvSkill
from skills.timer.skill import TimerSkill
from skills.todo.skill import TodoSkill
from skills.routine.skill import RoutineSkill
from skills.volume.skill import VolumeSkill
from skills.web_search.skill import WebSearchSkill
from cassandra.routine_manager import RoutineManager
from cassandra.calendar_service import CalendarService

TIMER_RINGS = 3  # quantas vezes o toque soa quando um timer acaba


class CassandraAssistant:
    def __init__(self) -> None:
        self.settings = load_settings()
        self.settings_store = SettingsStore()
        self.llm = LLMService()  # provider/modelo vêm do llm_settings (trocáveis pela UI)
        self.memory = ConversationMemory()
        self.sound_player = SoundPlayer()
        _ui_sounds = self.settings_store.get().get("sounds", {})
        self.sound_player.enabled = bool(_ui_sounds.get("enabled", True))
        self.sound_player.play(self.settings.startup_sound_path)
        self.music_pause = MusicPause()  # pausa o Spotify ao ouvir o nome e volta depois do pedido
        self._timer_interrupt = threading.Event()
        self.timer_manager = TimerManager(on_fire=self._timer_interrupt)
        self.routine_manager = RoutineManager(
            voice_output=None,  # preenchido abaixo após voice_output ser criado
            llm=self.llm,
            web_search_enabled=self.settings.web_search_enabled,
        )
        self.alarm_manager = AlarmManager(
            ring_sound_path=self.settings.ring_sound_path,
            sound_player=self.sound_player,
            on_alarm_fire=self.routine_manager.on_alarm_fire,
        )
        self.calendar = CalendarService()
        self.shopping_skill = ShoppingListSkill()
        self.todo_skill = TodoSkill()
        self.spotify_skill = SpotifySkill(self.llm)
        self.tv_skill = TvSkill(self.llm)
        _skills: list = [
            ClockSkill(),  # hora/data na hora, sem LLM
            AlarmSkill(self.alarm_manager),
            TimerSkill(self.timer_manager),
            self.tv_skill,  # antes do Spotify e do volume: "pausa a TV", "volume da TV" são dela
            self.spotify_skill,  # antes do volume: "abaixa a música" é o volume do Spotify
            VolumeSkill(),
            ScheduleSkill(self.calendar, self.llm),
            self.shopping_skill,
            self.todo_skill,
            RoutineSkill(self.routine_manager, self.alarm_manager, self.llm),
        ]
        if self.settings.web_search_enabled:
            from skills.web_search.skill import _client as maestro_client

            maestro_client.start()  # checa em segundo plano se o maestro está ligado
            from cassandra.agents_bridge import bridge  # noqa: PLC0415

            bridge.snapshot()  # já busca os agentes (em segundo plano): o 1º pedido não chega sem eles
            _skills.append(WebSearchSkill(self.llm, announce=lambda text: self.announce(text)))
        # announce: resultado de tarefa longa de outro agente (ex.: o IDE criando um site) é falado quando chega
        self.general_chat = GeneralChatSkill(self.llm, self.memory, announce=lambda text: self.announce(text))
        _skills.append(self.general_chat)
        self.router = SkillRouter(skills=_skills)
        if self.settings.input_mode in {"mic", "auto"}:
            # auto: escuta o microfone quando houver um; sem microfone, espera em silêncio até ele ser plugado.
            # A UI web funciona em qualquer modo (chat por texto + microfone ao mesmo tempo).
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
                assistant_name=self.settings.assistant_name,
                wake_words=self.settings.assistant_aliases or [self.settings.assistant_name],
                wake_word_engine=self.settings.wake_word_engine,
                transcription_provider=self.settings.transcription_provider,
                vosk_model_path=self.settings.vosk_model_path,
                wait_for_device=self.settings.input_mode == "auto",
                on_wake=self._on_wake,
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
        self._apply_voice_settings(self.settings_store.get().get("voice", {}))
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
        if self.settings.input_mode in {"mic", "auto"} and self.settings.mic_debug:
            print(
                f"[DEBUG] VAD threshold={self.settings.vad_energy_threshold} | "
                f"wake_silence={self.settings.vad_wake_silence_duration}s | "
                f"cmd_silence={self.settings.vad_silence_duration}s | "
                f"max={self.settings.vad_max_duration}s"
            )

        active_until: float | None = None
        # O pedido roda numa thread (ver _start_task): enquanto ela pensa, executa ou fala, o microfone continua
        # ouvindo — só o nome — e dizer "Cassandra" interrompe tudo para um pedido novo.
        self._task_thread: threading.Thread | None = None
        self._task_gen: int | None = None
        self._task_done: tuple[int, dict | None] | None = None
        self.input_source.on_barge = lambda: mic_monitor.set(phase="ouvindo o pedido")
        self._conv_nudges = 0  # vezes seguidas que ela puxou assunto sem resposta (modo conversa)

        while True:
            self._timer_interrupt.clear()
            active_until = self._finish_task(active_until)
            # Use a shorter silence threshold when waiting for the wake word.
            working = self._task_running()
            request, self._conv_request = getattr(self, "_conv_request", None), None
            if request == "start":
                # Modo conversa ligado (botão no header): ela cumprimenta e puxa assunto na hora.
                speech_state.cancel()
                self.sound_player.play(self.settings.on_sound_path)
                self.music_pause.pause()
                self._conv_nudges = 0
                mic_monitor.event("status", "Modo conversa ligado")
                self._start_prompt_task(conversation_mode.GREETING)
                active_until = None
                continue
            if request == "stop":
                speech_state.cancel()
                self._speak_in_background(conversation_mode.STOPPED, then_sound=self.settings.off_sound_path)
                self.music_pause.resume()
                mic_monitor.event("status", "Modo conversa desligado")
                active_until = None
                continue
            # Enquanto um pedido roda, só o nome vale (para interromper); a sessão reabre quando ele termina.
            in_active_session = active_until is not None and not working
            if mic_monitor.present is not False:
                mic_monitor.set(phase="trabalhando" if working else
                                "ouvindo o pedido" if in_active_session else "esperando o nome")
            # Na sessão a escuta tem prazo: sem ninguém começar a falar até lá, ela desativa na hora (com o som).
            wait = max(0.5, active_until - time.monotonic()) if in_active_session else None
            # Conversa: a pessoa pensa no meio da frase — pausa maior antes de dar a fala por terminada.
            silence = conversation_mode.SILENCE_SECONDS if in_active_session and conversation_mode.active() else None
            event = self.input_source.read(wake_phase=not in_active_session, max_wait=wait, silence=silence)

            # Handle fired timers before anything else
            if self.timer_manager.has_fired():
                for fired in self.timer_manager.pop_fired():
                    label = format_duration(fired.duration_seconds)
                    print(f"Cassandra: [TIMER] {label} finalizado!")
                    # Um toque depois do outro (tocados juntos se sobrepunham e soavam como um só).
                    for _ in range(TIMER_RINGS):
                        self.sound_player.play(self.settings.ring_sound_path, wait=True)
                        time.sleep(0.25)
                if active_until is not None:
                    active_until = time.monotonic() + self.settings.wake_timeout_seconds
                continue

            if event.exit_requested:
                self._shutdown_with_goodbye()
                break

            raw_text = event.text.strip()
            if not raw_text:
                # Silêncio/ruído. Na sessão, passado o prazo, desativa (som de desligar) e volta a esperar o nome;
                # antes disso segue ouvindo em silêncio (falar "não entendi" a cada ruído irritava).
                if active_until is not None and not working and time.monotonic() >= active_until:
                    if conversation_mode.active():
                        # Conversa: em vez de desativar, ela puxa assunto; depois de algumas vezes sem resposta,
                        # fica quieta (sem esquecer a conversa) e espera o nome.
                        if self._conv_nudges < conversation_mode.MAX_NUDGES:
                            self._conv_nudges += 1
                            mic_monitor.event("status", "Conversa: puxando assunto")
                            self._start_prompt_task(conversation_mode.NUDGE)
                            active_until = None
                            continue
                        self._conv_nudges = 0
                        self._speak_in_background(conversation_mode.GOING_QUIET,
                                                  then_sound=self.settings.off_sound_path)
                        active_until = None
                        self.music_pause.resume()
                        mic_monitor.event("status", "Conversa em pausa — voltou a esperar o nome")
                        continue
                    self.sound_player.play(self.settings.off_sound_path)
                    active_until = None
                    self.memory.clear()
                    self.music_pause.resume()  # chamou e não pediu nada: a música volta
                    mic_monitor.event("status", "Sessão encerrada por silêncio — voltou a esperar o nome")
                    if self.settings.mic_debug:
                        print("[SESSION] Sessao expirada. Memoria limpa.", flush=True)
                continue
            # Quem começou a falar dentro do prazo continua na sessão, mesmo que a fala termine depois dele.

            if self.settings.mic_debug and self.settings.input_mode in {"mic", "auto"}:
                print(f"[ROUTER] Recebido: {raw_text!r}")

            wake_detected, wake_command = self._parse_wake(raw_text)

            if (active_until is None or working) and not wake_detected:
                mic_monitor.event("ignored", f"Ignorado (sem o nome): “{raw_text}”")
                self._log_passive_heard(raw_text)
                if self.settings.mic_debug and self.settings.input_mode in {"mic", "auto"}:
                    print("[WAKE] Ignorado: wake word nao detectada.")
                continue

            if wake_detected and working:
                # Chamaram a Cassandra enquanto ela ainda trabalhava: o pedido anterior é abandonado.
                speech_state.cancel()
                mic_monitor.event("status", "Pedido anterior interrompido")
            if wake_detected:
                if not getattr(event, "wake_signaled", False):
                    self.sound_player.play(self.settings.on_sound_path)
                self.music_pause.pause()  # já pausada pelo _on_wake na maioria das vezes; repetir não faz nada
                command = wake_command
                command_source = "wake_inline"
                if not command:
                    # Só o nome: abre a sessão e espera o pedido. Sem fala até o prazo, desativa (no topo do loop).
                    mic_monitor.event("status", "Ativada — pode falar o pedido")
                    active_until = time.monotonic() + self.settings.wake_timeout_seconds
                    continue
            else:
                # Active session: no wake word required.
                command = raw_text
                command_source = "active_session"

            if not command:
                active_until = time.monotonic() + self.settings.wake_timeout_seconds
                continue

            self._conv_nudges = 0
            if conversation_mode.is_start(command) and not conversation_mode.active():
                self.set_conversation_mode(True)
                continue
            if conversation_mode.is_stop(command) and conversation_mode.active():
                self.set_conversation_mode(False)
                continue
            mic_monitor.event("command", f"Pedido: “{command}”")
            mic_monitor.set(phase="pensando")
            self._start_task(command, command_source)
            active_until = None  # a sessão reabre quando o pedido terminar (_finish_task)

    # ── Pedido em segundo plano (interrompível) ─────────────────────────────

    def _task_running(self) -> bool:
        """Há um pedido da geração atual em andamento? (Um interrompido não conta.)"""
        thread = self._task_thread
        return (thread is not None and thread.is_alive() and self._task_gen is not None
                and not speech_state.cancelled(self._task_gen))

    def _start_task(self, command: str, source: str) -> None:
        gen = speech_state.generation()

        def run() -> None:
            speech_state.task_begin(gen)
            result = None
            try:
                result = self.process_text_command(command, source=source, speak_response=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[ERRO] Pedido falhou: {exc}", flush=True)
            finally:
                self._task_done = (gen, result)
                self._timer_interrupt.set()  # acorda o microfone para reabrir a sessão (ou seguir esperando)

        self._task_gen = gen
        self._task_thread = threading.Thread(target=run, name="cassandra-task", daemon=True)
        self._task_thread.start()

    def _finish_task(self, active_until: float | None) -> float | None:
        """Pedido terminou: registra e desativa (no modo conversa, reabre a escuta). Interrompido: ignora em silêncio."""
        done, self._task_done = self._task_done, None
        if done is None:
            return active_until
        gen, result = done
        if speech_state.cancelled(gen):
            return active_until  # a pessoa já chamou a Cassandra de novo: nada de bip nem sessão do pedido velho
        if result is not None:
            response = result["response"]
            print(f"Cassandra: {response}")
            mic_monitor.event("response", f"Resposta: “{response}”")
        if result is not None and result["dismissed"]:
            if conversation_mode.set_active(False):
                mic_monitor.event("status", "Modo conversa desligado (despedida)")
            self.music_pause.resume()
            return None
        if not conversation_mode.active():
            # Pedido atendido: ela desativa e só volta a ouvir quando chamarem o nome de novo (reabrir a escuta
            # sozinha fazia ela pegar a TV/conversas da casa como pedido). Música pausada para ouvir o pedido volta
            # agora, se o pedido não mexeu nela. Só o modo conversa segue ouvindo depois de responder.
            if self.music_pause.active:
                self.music_pause.resume()
                mic_monitor.event("status", "Pedido respondido — música de volta")
            else:
                mic_monitor.event("status", "Pedido respondido — esperando o nome de novo")
            return None
        # Modo conversa: bip de que está ouvindo de novo e espera a pessoa responder.
        self.sound_player.play(self.settings.on_sound_path)
        return time.monotonic() + self._session_seconds()

    def _session_seconds(self) -> float:
        """Quanto ela espera a pessoa voltar a falar depois de responder (bem mais no modo conversa)."""
        return conversation_mode.LISTEN_SECONDS if conversation_mode.active() else self.settings.wake_timeout_seconds

    # ── Modo conversa ───────────────────────────────────────────────────────

    def get_conversation_mode(self) -> dict:
        return {"active": conversation_mode.active()}

    def set_conversation_mode(self, on: bool) -> dict:
        """Liga/desliga (botão no header ou por voz). O loop do microfone faz o resto: cumprimenta ou se despede."""
        if conversation_mode.set_active(on):
            self._conv_request = "start" if on else "stop"
            self._timer_interrupt.set()  # acorda o microfone para agir já
        return self.get_conversation_mode()

    def _start_prompt_task(self, instruction: str) -> None:
        """Ela mesma fala primeiro (cumprimento ao ligar a conversa, ou puxando assunto no silêncio), no estilo
        da conversa e com o que já foi dito. Roda como um pedido: o nome interrompe e a sessão reabre no fim."""
        gen = speech_state.generation()

        def run() -> None:
            speech_state.task_begin(gen)
            result = None
            try:
                with self._state_lock:
                    stream = self.llm.answer_stream(user_text=instruction,
                                                    system_prompt=self.general_chat._build_system_prompt(),
                                                    history=self.memory.get_messages())
                    response = self.voice_output.speak_stream(stream).strip()
                    if response and not speech_state.cancelled(gen):
                        self.memory.add_assistant(response)
                        self._append_history(role="assistant", content=response, source="assistant", kind="chat")
                        result = {"response": response, "dismissed": False}
            except Exception as exc:  # noqa: BLE001
                print(f"[CONVERSA] Falhou ao puxar assunto: {exc}", flush=True)
            finally:
                self._task_done = (gen, result)
                self._timer_interrupt.set()

        self._task_gen = gen
        self._task_thread = threading.Thread(target=run, name="cassandra-conversa", daemon=True)
        self._task_thread.start()

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
                said: list[str] = []
                stream = self._notices(skill.handle_stream(text), said, speak_now=not speak_response)
                if speak_response:
                    response = self.voice_output.speak_stream(stream)
                    for note in said:  # o aviso já foi dito e registrado à parte: a resposta é só o resultado
                        if response.startswith(note):
                            response = response[len(note):].strip()
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

    def _notices(self, stream, said: list[str], speak_now: bool):
        """Separa o aviso ("Deixa eu dar uma olhada nisso.") do resultado: ele vira uma mensagem própria no chat na
        hora, antes de a tarefa começar, e é dito na hora. Antes o aviso saía colado no resultado, numa resposta só,
        quando tudo terminava. Na voz o aviso segue no streaming (é falado primeiro, enquanto a tarefa roda); no chat
        de texto (speak_now) ele é falado em segundo plano e sai da resposta."""
        for token in stream:
            if isinstance(token, notices.Notice):
                note = token.strip()
                said.append(note)
                self._append_history(role="assistant", content=note, source="assistant", kind="chat")
                if speak_now:
                    self._speak_in_background(note)
                    continue
            yield token

    def process_web_message(self, message: str) -> dict[str, str | bool]:
        """Handles web messages with wake-word flow similar to voice mode."""
        text = (message or "").strip()
        if not text:
            raise ValueError("Message cannot be empty.")

        with self._state_lock:
            wake_detected, wake_command = self._parse_wake(text)
            # No chat de texto quem escreve já está falando com ela: não precisa dizer o nome antes (isso é só
            # para a voz, onde o microfone ouve a casa inteira). "cassandra, ..." continua valendo.
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
                command_source = "web_active_session" if self._web_session_active else "web_direct"

        # A UI recebe o texto na hora e a fala sai em segundo plano. Esperar a fala terminar antes de responder
        # estourava o limite do proxy do site (~26 s no Netlify) com a voz grátis: ela falava, mas a UI dava erro.
        result = self.process_text_command(
            command,
            source=command_source,
            speak_response=False,
        )
        with self._state_lock:
            if result["dismissed"]:
                self._web_session_active = False
            else:
                self._web_session_active = True
        self._speak_in_background(
            result["response"],
            then_sound=self.settings.off_sound_path if result["dismissed"] else None,
        )
        return {
            "response": result["response"],
            "dismissed": result["dismissed"],
            "activated": True,
        }

    def _speak_in_background(self, text: str, then_sound: str | None = None) -> None:
        def run() -> None:
            try:
                # speak_stream divide em frases e gera a próxima enquanto a atual toca
                self.voice_output.speak_stream(iter([text]))
            except Exception as exc:  # noqa: BLE001
                print(f"[VOZ] Erro ao falar a resposta do chat: {exc}", flush=True)
            if then_sound:
                self.sound_player.play(then_sound)

        threading.Thread(target=run, name="web-speech", daemon=True).start()

    def announce(self, text: str) -> dict[str, bool]:
        """Fala exatamente `text` na casa (aviso), sem passar pelo LLM: toca o som de atenção, registra no
        histórico e fala em segundo plano. Respeita a voz desligada nas configurações."""
        text = (text or "").strip()
        if not text:
            raise ValueError("text is required")
        with self._state_lock:
            self._append_history(role="assistant", content=text, source="api_speak", kind="announcement")
        spoken = bool(self.voice_output.enabled)
        if spoken:
            self.sound_player.play(self.settings.on_sound_path)
            self._speak_in_background(text)
        return {"ok": True, "spoken": spoken}

    def get_conversation_history(self) -> list[dict[str, str]]:
        # Sem a trava: um pedido em andamento a segura até terminar (uma pesquisa leva um minuto) e o chat não via
        # o aviso já dito ("deixa eu dar uma olhada") até tudo acabar. Copiar a lista é seguro sem ela.
        return [dict(item) for item in list(self._conversation_history)]

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
        date_ymd: str | None = None,
        day_of_month: int | None = None,
    ) -> dict:
        alarm = self.alarm_manager.add_alarm(
            time_hhmm=time_hhmm,
            recurring_daily=recurring_daily,
            label=label,
            days_of_week=days_of_week,
            date_ymd=date_ymd,
            day_of_month=day_of_month,
        )
        return {
            "id": alarm.id,
            "label": alarm.label,
            "time_hhmm": alarm.time_hhmm,
            "recurring_daily": alarm.recurring_daily,
            "days_of_week": alarm.days_of_week,
            "next_trigger_at": alarm.next_trigger_at,
            "enabled": alarm.enabled,
            "date_ymd": alarm.date_ymd,
            "day_of_month": alarm.day_of_month,
        }

    def get_ui_settings(self) -> dict:
        s = self.settings_store.get()
        # Augment with read-only runtime info from .env/config
        s["_runtime"] = {
            "assistant_name": self.settings.assistant_name,
            "input_mode": self.settings.input_mode,
            "openai_model": llm_settings.describe_active(),
            "llm": llm_settings.describe_active(),
            "tts_model_env": self.settings.tts_model,
            "tts_voice_env": self.settings.tts_voice,
        }
        return s

    def save_ui_settings(self, patch: dict) -> dict:
        updated = self.settings_store.update(patch)
        # Apply voice settings dynamically without restart
        self._apply_voice_settings(updated.get("voice", {}))
        # Apply sounds toggle dynamically
        sounds_on = bool(updated.get("sounds", {}).get("enabled", True))
        self.sound_player.enabled = sounds_on
        return self.get_ui_settings()

    def reset_ui_settings(self) -> dict:
        self.settings_store.reset()
        self._apply_voice_settings(self.settings_store.get().get("voice", {}))
        return self.get_ui_settings()

    def _apply_voice_settings(self, v: dict) -> None:
        """Configurações de voz da UI (data/ui_settings.json) — no start e ao salvar, sem reiniciar."""
        vo = self.voice_output
        vo.enabled = bool(v.get("enabled", True))
        vo.tts_voice = str(v.get("tts_voice", self.settings.tts_voice))
        vo.tts_model = str(v.get("tts_model", self.settings.tts_model))
        vo.fallback_lang = str(v.get("fallback_lang", self.settings.voice_lang))
        vo.fallback_rate = int(v.get("fallback_rate", self.settings.voice_rate))
        vo.set_engine(str(v.get("engine", "auto")))

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

    def _on_wake(self) -> None:
        """Nome reconhecido ao vivo: som de ativação e pausa da música, antes mesmo do pedido."""
        self.sound_player.play(self.settings.on_sound_path)
        self.music_pause.pause()

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

    _DISMISSALS = (
        "tchau", "dispensada", "pode ir", "obrigado", "obrigada", "valeu", "ate logo", "ate mais", "ate depois",
        "pode descansar", "foi isso", "ok obrigado", "ok obrigada", "so isso", "era so isso", "e so isso",
        "nada nao", "deixa pra la", "esquece", "pode dormir", "boa noite", "falou", "brigado", "brigada",
    )

    def _is_dismissal(self, command: str) -> bool:
        """A pessoa está encerrando a conversa ("tchau", "valeu", "era só isso")? Checagem local, instantânea —
        antes era uma chamada ao LLM em todo pedido (~1 s a mais em cada resposta). Só frases curtas contam, e
        nunca com continuação ("valeu, agora toca...")."""
        t = unicodedata.normalize("NFKD", command.lower())
        t = "".join(c for c in t if not unicodedata.combining(c))
        t = re.sub(r"[^a-z ]+", " ", t)
        aliases = self.settings.assistant_aliases or [self.settings.assistant_name]
        t = re.sub(r"\b(" + "|".join(map(re.escape, aliases)) + r")\b", " ", t)
        t = " ".join(t.split())
        if not t or len(t.split()) > 5 or re.search(r"\b(mas|agora|e ai|toca|liga|desliga|coloca|me)\b", t):
            return False
        return any(t == d or t.startswith(d + " ") or t.endswith(" " + d) for d in self._DISMISSALS)

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
