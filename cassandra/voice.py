from __future__ import annotations

import os
import queue
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Iterator


def _split_sentences(text: str) -> tuple[list[str], str]:
    """Split text into complete sentences, return (sentences, leftover)."""
    sentences: list[str] = []
    last = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in ".!?":
            if i + 1 >= len(text) or text[i + 1] in " \n\t":
                s = text[last : i + 1].strip()
                if s:
                    sentences.append(s)
                last = i + 1
        elif ch == "\n" and i > last:
            s = text[last:i].strip()
            if s:
                sentences.append(s)
            last = i + 1
        i += 1
    return sentences, text[last:]


class VoiceOutput:
    """Text-to-speech output.

    Primary backend: OpenAI TTS (neural, natural-sounding).
    Fallback: espeak / spd-say (robotic, but no API cost).

    Playback is always blocking so the microphone is not re-opened
    while Cassandra is still speaking.
    """

    def __init__(
        self,
        enabled: bool,
        llm=None,
        tts_voice: str = "nova",
        tts_model: str = "tts-1",
        fallback_lang: str = "pt-br",
        fallback_rate: int = 165,
    ) -> None:
        self.enabled = enabled
        self.llm = llm
        self.tts_voice = tts_voice
        self.tts_model = tts_model
        self.fallback_lang = fallback_lang
        self.fallback_rate = fallback_rate
        self._player = self._detect_player() if enabled else None
        self._local_tts = self._detect_local_tts() if enabled else None

    def speak(self, text: str) -> None:
        if not self.enabled:
            return
        cleaned = text.strip()
        if not cleaned:
            return

        if self.llm and self._player:
            try:
                self._speak_openai(cleaned)
                return
            except Exception:
                pass  # fall through to local TTS

        self._speak_local(cleaned)

    def speak_stream(self, token_iter: Iterator[str]) -> str:
        """Stream LLM tokens, pipeline TTS per sentence, return full text.

        While sentence N is playing, TTS for sentence N+1 is already being
        requested — cutting the perceived latency roughly in half for long
        responses.
        """
        if not self.enabled:
            return "".join(token_iter)

        sentence_q: queue.Queue[str | None] = queue.Queue()
        audio_q: queue.Queue[tuple[str, bytes | None] | None] = queue.Queue(maxsize=2)

        def collect() -> None:
            buf = ""
            for token in token_iter:
                buf += token
                sentences, buf = _split_sentences(buf)
                for s in sentences:
                    sentence_q.put(s)
            if buf.strip():
                sentence_q.put(buf.strip())
            sentence_q.put(None)

        def generate_tts() -> None:
            while True:
                sentence = sentence_q.get()
                if sentence is None:
                    audio_q.put(None)
                    break
                if self.llm and self._player:
                    try:
                        audio = self.llm.synthesize_speech(
                            sentence, model=self.tts_model, voice=self.tts_voice
                        )
                        audio_q.put((sentence, audio))
                        continue
                    except Exception:
                        pass
                audio_q.put((sentence, None))

        threading.Thread(target=collect, daemon=True).start()
        threading.Thread(target=generate_tts, daemon=True).start()

        parts: list[str] = []
        while True:
            item = audio_q.get()
            if item is None:
                break
            sentence, audio = item
            parts.append(sentence)
            if audio:
                self._play_audio_bytes(audio)
            else:
                self._speak_local(sentence)

        return " ".join(parts)

    def _play_audio_bytes(self, audio: bytes) -> None:
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp.write(audio)
        tmp.close()
        try:
            cmd = self._build_player_cmd(self._player, tmp.name)
            if cmd:
                subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
        finally:
            os.unlink(tmp.name)

    def _speak_openai(self, text: str) -> None:
        audio_bytes = self.llm.synthesize_speech(
            text, model=self.tts_model, voice=self.tts_voice
        )
        self._play_audio_bytes(audio_bytes)

    def _speak_local(self, text: str) -> None:
        if not self._local_tts:
            return
        cmd = self._build_local_cmd(self._local_tts, text)
        if cmd:
            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )

    @staticmethod
    def _detect_player() -> str | None:
        for player in ["ffplay", "mpg123", "mpv", "cvlc", "play"]:
            if shutil.which(player):
                return player
        return None

    @staticmethod
    def _detect_local_tts() -> str | None:
        if shutil.which("espeak"):
            return "espeak"
        if shutil.which("spd-say"):
            return "spd-say"
        return None

    @staticmethod
    def _build_player_cmd(player: str, path: str) -> list[str] | None:
        if player == "ffplay":
            return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path]
        if player == "mpg123":
            return ["mpg123", "-q", path]
        if player == "mpv":
            return ["mpv", "--no-video", "--really-quiet", path]
        if player == "cvlc":
            return ["cvlc", "--play-and-exit", "--quiet", path]
        if player == "play":
            return ["play", "-q", path]
        return None

    def _build_local_cmd(self, backend: str, text: str) -> list[str] | None:
        if backend == "espeak":
            return ["espeak", "-v", self.fallback_lang, "-s", str(self.fallback_rate), text]
        if backend == "spd-say":
            return ["spd-say", "-l", self.fallback_lang, text]
        return None
