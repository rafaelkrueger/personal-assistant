from __future__ import annotations

import glob
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher

from cassandra import llm_settings
from cassandra.openai_client import LLMService

_OPENAI_RETRY_AFTER = 600  # depois de uma falha da OpenAI (ex.: sem créditos), usa só o local por 10 min


@dataclass
class InputEvent:
    text: str
    exit_requested: bool = False


class TextInputSource:
    def read(self, wake_phase: bool = False) -> InputEvent:
        _ = wake_phase
        raw_text = input("\nVoce: ").strip()
        if raw_text.lower() in {"sair", "exit", "quit"}:
            return InputEvent(text="", exit_requested=True)
        return InputEvent(text=raw_text)


class MicrophoneInputSource:
    """Captures one complete spoken utterance per read() call using VAD.

    Unlike the previous chunked approach, this class streams audio continuously
    via pyaudio and uses energy-based VAD to detect when the user starts and
    finishes speaking. The full utterance is sent to the transcription API in
    one shot, eliminating chunk-boundary artifacts and mid-sentence cut-offs.

    With wake_word_engine="local" (default), while waiting for the name each
    utterance is first checked on the device by Vosk (cassandra/local_speech.py):
    without the name it is discarded there and nothing goes to the API. Only
    utterances with the name (and everything said during an active session)
    are transcribed — by OpenAI or locally, per transcription_provider.
    """

    def __init__(
        self,
        llm: LLMService,
        transcription_model: str,
        transcription_language: str,
        transcription_prompt: str,
        vad_energy_threshold: int = 400,
        vad_silence_duration: float = 0.8,
        vad_wake_silence_duration: float = 0.5,
        vad_max_duration: float = 30.0,
        interrupt_event: threading.Event | None = None,
        debug: bool = True,
        assistant_name: str = "cassandra",
        wake_words: list[str] | None = None,
        wake_word_engine: str = "local",
        transcription_provider: str = "auto",
        vosk_model_path: str = "models/vosk-model-small-pt-0.3",
        wait_for_device: bool = False,
    ) -> None:
        self.llm = llm
        self.transcription_model = transcription_model
        self.transcription_language = transcription_language
        self.transcription_prompt = transcription_prompt
        self.vad_wake_silence_duration = vad_wake_silence_duration
        self.interrupt_event = interrupt_event
        self.debug = debug
        self._last_capture_error_at = 0.0
        self.assistant_name = assistant_name
        self.wait_for_device = wait_for_device
        self._mic_present: bool | None = None
        self.transcription_provider = transcription_provider
        self._openai_down_until = 0.0

        self.local = None
        if wake_word_engine == "local" or transcription_provider in {"auto", "local"}:
            from cassandra.local_speech import LocalSpeech  # noqa: PLC0415

            self.local = LocalSpeech(wake_words or [assistant_name], model_path=vosk_model_path, debug=debug)
            self.local.preload()
        self.local_wake = wake_word_engine == "local"

        from cassandra.vad_recorder import VadRecorder  # noqa: PLC0415

        self._recorder = VadRecorder(
            energy_threshold=vad_energy_threshold,
            silence_duration=vad_silence_duration,
            max_duration=vad_max_duration,
        )

    def read(self, wake_phase: bool = False) -> InputEvent:
        """Block until a complete utterance is spoken, then transcribe it.

        Args:
            wake_phase: When True, uses the shorter wake-word silence threshold
                so activation is faster after the user says just the assistant name.
        """
        if self.wait_for_device and not self._check_microphone():
            time.sleep(3)
            return InputEvent(text="")
        silence_override = self.vad_wake_silence_duration if wake_phase else None
        try:
            text = self._capture_and_transcribe(silence_override, wake_phase=wake_phase)
        except Exception as exc:  # noqa: BLE001
            now = time.monotonic()
            if now - self._last_capture_error_at > 5.0:
                self._last_capture_error_at = now
                print(f"[MIC] Entrada de audio indisponivel: {exc}")
            self._recorder.close()  # reabre na próxima: o PortAudio só enxerga aparelhos novos ao reiniciar
            time.sleep(1.0)
            return InputEvent(text="")
        if text.lower() in {"sair", "exit", "quit"}:
            return InputEvent(text="", exit_requested=True)
        return InputEvent(text=text)

    def _capture_and_transcribe(self, silence_duration: float | None = None, wake_phase: bool = False) -> str:
        wav_path = self._recorder.record_utterance(
            silence_duration=silence_duration,
            interrupt_event=self.interrupt_event,
        )
        if not wav_path:
            return ""

        try:
            if wake_phase and self.local_wake and self._local_ready():
                # Esperando o nome: checa no próprio aparelho; sem o nome, nada vai para a API.
                if not self.local.heard_wake_word(wav_path):
                    return ""
                if self.local.last_only_name:
                    text = self.assistant_name  # só o nome: abre a sessão sem gastar transcrição
                else:
                    text = self._with_wake_word(self._transcribe(wav_path))
            else:
                text = self._transcribe(wav_path)
        finally:
            os.unlink(wav_path)

        text = (text or "").strip()

        if self.debug:
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[MIC {ts}] {text or '<silencio>'}")

        return text

    def _check_microphone(self) -> bool:
        """Há algum aparelho de captura (ex.: microfone USB)? Loga só quando muda."""
        present = bool(glob.glob("/proc/asound/card*/pcm*c"))
        if present != self._mic_present:
            if present:
                print("[MIC] Microfone detectado — ouvindo (diga o nome para chamar).", flush=True)
                self._recorder.close()  # o PortAudio precisa reiniciar para ver o aparelho novo
            else:
                print("[MIC] Nenhum microfone conectado — aguardando você plugar um. "
                      "O chat da UI continua funcionando.", flush=True)
            self._mic_present = present
        return present

    def _local_ready(self) -> bool:
        return self.local is not None and self.local.available()

    def _transcribe(self, wav_path: str) -> str:
        provider = self.transcription_provider
        use_openai = provider == "openai" or (
            provider == "auto"
            and bool(llm_settings.get()["openai_api_key"])
            and time.monotonic() >= self._openai_down_until
        )
        if use_openai:
            try:
                return self.llm.transcribe_audio_file(
                    wav_path,
                    model=self.transcription_model,
                    language=self.transcription_language,
                    prompt=self.transcription_prompt,
                )
            except Exception as exc:  # noqa: BLE001
                if provider == "openai" or not self._local_ready():
                    raise
                self._openai_down_until = time.monotonic() + _OPENAI_RETRY_AFTER
                print(f"[MIC] Transcrição da OpenAI falhou ({exc}); usando a local por 10 min.")
        if not self._local_ready():
            raise RuntimeError("Sem transcrição disponível: nem chave da OpenAI nem modelo local (Vosk).")
        return self.local.transcribe(wav_path)

    def _with_wake_word(self, text: str) -> str:
        """O nome foi detectado localmente, mas a transcrição completa às vezes o erra ("sandra que horas
        são"). Garante que o texto comece pelo nome, para o assistente reconhecer a ativação."""
        words = (text or "").strip().split(" ", 1)
        first = words[0].strip(" ,.:;!?").lower() if words and words[0] else ""
        rest = words[1].strip() if len(words) > 1 else ""
        if first and SequenceMatcher(None, first, self.assistant_name.lower()).ratio() >= 0.6:
            return f"{self.assistant_name}, {rest}".strip(" ,")
        return f"{self.assistant_name}, {text}".strip(" ,")

    def close(self) -> None:
        self._recorder.close()
