from __future__ import annotations

import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
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


# Players em ordem de preferência. pw-play (PipeWire) vem primeiro: manda o áudio direto para a saída padrão
# (ex.: a soundbar Bluetooth). Sem o pacote pipewire-alsa, os players via ALSA (ffplay, mpg123...) tocam no
# dispositivo de hardware padrão (HDMI/fone do Pi) — ninguém ouve.
PLAYERS = ["pw-play", "ffplay", "mpg123", "mpv", "cvlc", "play"]

_OPENAI_RETRY_AFTER = 600  # depois de uma falha da voz da OpenAI (ex.: sem créditos), só voz grátis por 10 min

# Variante feminina do espeak-ng. Medido num Raspberry Pi 3: ~80 ms por frase. As alternativas femininas
# grátis foram bem mais lentas (Edge TTS ~4,5 s, Kokoro ~25 s) e o Piper não tem voz feminina em português.
ESPEAK_FEMALE_VARIANT = "f4"


def detect_player() -> str | None:
    for player in PLAYERS:
        if shutil.which(player):
            return player
    return None


def player_command(player: str, path: str) -> list[str] | None:
    if player == "pw-play":
        return ["pw-play", path]
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


class VoiceOutput:
    """Text-to-speech output.

    Engines:
      - openai: OpenAI TTS (the most natural; paid; voice "nova" is female).
      - espeak: espeak-ng with a female variant (free, instant, robotic).
      - piper: Piper, neural voice running on the device (free, natural, but male and ~3 s per sentence on
        a Pi 3; only loaded when chosen).
    engine="auto" (default) uses OpenAI while there's a key and it works; if it fails (e.g. no credits) it
    switches to the female espeak and skips OpenAI for 10 minutes. Every engine falls back to espeak, so a
    missing key or credits never leaves Cassandra silent.

    Playback is always blocking so the microphone is not re-opened
    while Cassandra is still speaking.
    """

    ENGINES = ("auto", "openai", "piper", "espeak")

    def __init__(
        self,
        enabled: bool,
        llm=None,
        tts_voice: str = "nova",
        tts_model: str = "tts-1",
        fallback_lang: str = "pt-br",
        fallback_rate: int = 165,
        engine: str = "auto",
        piper_model: str | None = None,
    ) -> None:
        from cassandra.piper_tts import DEFAULT_VOICE, PiperTTS  # noqa: PLC0415

        self.enabled = enabled
        self.llm = llm
        self.tts_voice = tts_voice
        self.tts_model = tts_model
        self.fallback_lang = fallback_lang
        self.fallback_rate = fallback_rate
        self.engine = engine if engine in self.ENGINES else "auto"
        self._player = detect_player()
        self._espeak = shutil.which("espeak-ng") or shutil.which("espeak")
        self._piper = PiperTTS(piper_model or DEFAULT_VOICE)  # só carrega se o motor escolhido for o Piper
        if self.engine == "piper":
            self._piper.preload()
        self._openai_down_until = 0.0
        self._last_engine: str | None = None
        self._play_lock = threading.Lock()  # uma fala por vez (chat web em segundo plano + microfone)

    # ── API pública ───────────────────────────────────────────────────────────

    def speak(self, text: str) -> None:
        if not self.enabled:
            return
        cleaned = text.strip()
        if not cleaned:
            return
        path = self._synthesize(cleaned)
        if path:
            self._play_file(path)

    def speak_stream(self, token_iter: Iterator[str]) -> str:
        """Stream LLM tokens, pipeline TTS per sentence, return full text.

        While sentence N is playing, TTS for sentence N+1 is already being
        generated — cutting the perceived latency roughly in half for long
        responses.
        """
        if not self.enabled:
            return "".join(token_iter)

        sentence_q: queue.Queue[str | None] = queue.Queue()
        audio_q: queue.Queue[tuple[str, str | None] | None] = queue.Queue(maxsize=2)

        errors: list[BaseException] = []

        def collect() -> None:
            # Sempre sinaliza o fim (None), mesmo se o LLM falhar no meio (sem crédito, rede...). Sem isso o
            # loop abaixo espera para sempre e trava o assistente inteiro (quem chamou segura o _state_lock).
            try:
                buf = ""
                for token in token_iter:
                    buf += token
                    sentences, buf = _split_sentences(buf)
                    for s in sentences:
                        sentence_q.put(s)
                if buf.strip():
                    sentence_q.put(buf.strip())
            except BaseException as exc:  # noqa: BLE001 — repassado para quem chamou, depois do loop
                errors.append(exc)
            finally:
                sentence_q.put(None)

        def generate_tts() -> None:
            while True:
                sentence = sentence_q.get()
                if sentence is None:
                    audio_q.put(None)
                    break
                audio_q.put((sentence, self._synthesize(sentence)))

        threading.Thread(target=collect, daemon=True).start()
        threading.Thread(target=generate_tts, daemon=True).start()

        parts: list[str] = []
        while True:
            item = audio_q.get()
            if item is None:
                break
            sentence, path = item
            parts.append(sentence)
            if path:
                self._play_file(path)

        if errors:
            raise errors[0]
        return " ".join(parts)

    # ── Síntese ───────────────────────────────────────────────────────────────

    def set_engine(self, engine: str) -> None:
        self.engine = engine if engine in self.ENGINES else "auto"
        if self.engine == "piper":
            self._piper.preload()  # ~16 s num Pi 3, em segundo plano

    def _engine_order(self) -> list[str]:
        if self.engine == "espeak":
            return ["espeak"]
        if self.engine == "piper":
            return ["piper", "espeak"]
        if self.engine == "openai":
            return ["openai", "espeak"]
        # auto: OpenAI só se houver chave e ela não tiver falhado há pouco; senão a voz feminina grátis
        from cassandra import llm_settings  # noqa: PLC0415

        openai_ok = bool(llm_settings.get()["openai_api_key"]) and time.monotonic() >= self._openai_down_until
        return (["openai"] if openai_ok else []) + ["espeak"]

    def _synthesize(self, text: str) -> str | None:
        """Gera o áudio da frase num arquivo temporário (quem toca apaga). None se nenhum motor conseguiu."""
        for engine in self._engine_order():
            try:
                path = getattr(self, f"_synth_{engine}")(text)
            except Exception as exc:  # noqa: BLE001
                if engine == "openai":
                    self._openai_down_until = time.monotonic() + _OPENAI_RETRY_AFTER
                    print(f"[VOZ] Voz da OpenAI falhou ({str(exc)[:120]}); usando a voz grátis por 10 min.", flush=True)
                elif self._last_engine != f"{engine}-erro":
                    print(f"[VOZ] {engine} falhou: {exc}", flush=True)
                    self._last_engine = f"{engine}-erro"
                continue
            if path:
                if self._last_engine != engine:
                    print(f"[VOZ] Falando com: {engine}", flush=True)
                    self._last_engine = engine
                return path
        return None

    def _synth_openai(self, text: str) -> str | None:
        if not self.llm:
            return None
        audio = self.llm.synthesize_speech(text, model=self.tts_model, voice=self.tts_voice)
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp.write(audio)
        tmp.close()
        return tmp.name

    def _synth_piper(self, text: str) -> str | None:
        # Espera no máximo alguns segundos pelo carregamento; se ainda não estiver pronto, cai no espeak.
        if not self._piper.available(wait=5):
            raise RuntimeError("voz local ainda carregando ou indisponível")
        return self._piper.synthesize_to_file(text, rate_wpm=self.fallback_rate)

    def _synth_espeak(self, text: str) -> str | None:
        if not self._espeak:
            return None
        lang = self.fallback_lang
        if lang == "pt":
            lang = "pt-br"  # no espeak-ng, "pt" é português de Portugal
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        voice = f"{lang}+{ESPEAK_FEMALE_VARIANT}"
        subprocess.run(
            [self._espeak, "-v", voice, "-s", str(self.fallback_rate), "-w", tmp.name, text],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return tmp.name

    # ── Reprodução ────────────────────────────────────────────────────────────

    def _play_file(self, path: str) -> None:
        try:
            cmd = player_command(self._player, path) if self._player else None
            if cmd:
                with self._play_lock:
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        finally:
            os.unlink(path)
