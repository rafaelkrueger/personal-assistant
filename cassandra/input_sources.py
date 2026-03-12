from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime

from cassandra.openai_client import LLMService


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
    ) -> None:
        self.llm = llm
        self.transcription_model = transcription_model
        self.transcription_language = transcription_language
        self.transcription_prompt = transcription_prompt
        self.vad_wake_silence_duration = vad_wake_silence_duration
        self.interrupt_event = interrupt_event
        self.debug = debug
        self._last_capture_error_at = 0.0

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
        silence_override = self.vad_wake_silence_duration if wake_phase else None
        try:
            text = self._capture_and_transcribe(silence_override)
        except Exception as exc:  # noqa: BLE001
            now = time.monotonic()
            if now - self._last_capture_error_at > 5.0:
                self._last_capture_error_at = now
                print(f"[MIC] Entrada de audio indisponivel: {exc}")
            time.sleep(1.0)
            return InputEvent(text="")
        if text.lower() in {"sair", "exit", "quit"}:
            return InputEvent(text="", exit_requested=True)
        return InputEvent(text=text)

    def _capture_and_transcribe(self, silence_duration: float | None = None) -> str:
        wav_path = self._recorder.record_utterance(
            silence_duration=silence_duration,
            interrupt_event=self.interrupt_event,
        )
        if not wav_path:
            return ""

        try:
            text = self.llm.transcribe_audio_file(
                wav_path,
                model=self.transcription_model,
                language=self.transcription_language,
                prompt=self.transcription_prompt,
            )
        finally:
            os.unlink(wav_path)

        text = (text or "").strip()

        if self.debug:
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[MIC {ts}] {text or '<silencio>'}")

        return text

    def close(self) -> None:
        self._recorder.close()
