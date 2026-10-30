from __future__ import annotations

import hashlib
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape

from cassandra import usage_log
from cassandra import speech_state


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
_AZURE_RETRY_AFTER = 600  # idem para o Azure (ex.: franquia grátis do mês esgotada): usa a próxima voz por 10 min

# Voz do Azure (Microsoft Speech). Chave e região no .env (AZURE_SPEECH_KEY, AZURE_SPEECH_REGION); o plano
# gratuito F0 dá 500 mil caracteres/mês e, esgotado, só recusa (sem cobrar) — aí a OpenAI assume.
AZURE_DEFAULT_VOICE = "pt-BR-FranciscaNeural"


def _azure_config() -> tuple[str, str, str]:
    """(chave, região, voz) — das Configurações > Modelo de IA (llm_settings; o .env é o padrão). Vale na hora."""
    from cassandra import llm_settings  # noqa: PLC0415

    s = llm_settings.get()
    return (s.get("azure_speech_key", ""), s.get("azure_speech_region") or "brazilsouth",
            s.get("azure_tts_voice") or AZURE_DEFAULT_VOICE)


_voices_cache: tuple[float, str, list[dict]] = (0.0, "", [])


def azure_voices() -> list[dict]:
    """Vozes em pt-BR da conta do Azure (nome, rótulo, gênero), para o seletor da UI. Cache de 1 h."""
    global _voices_cache
    import json  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    key, region, _voice = _azure_config()
    if not key:
        return []
    at, cached_for, voices = _voices_cache
    if voices and cached_for == f"{region}|{key[-6:]}" and time.monotonic() - at < 3600:
        return voices
    req = urllib.request.Request(
        f"https://{region}.tts.speech.microsoft.com/cognitiveservices/voices/list",
        headers={"Ocp-Apim-Subscription-Key": key, "User-Agent": "cassandra"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    gender = {"Female": "feminina", "Male": "masculina"}
    voices = sorted(
        ({"name": v["ShortName"], "label": v.get("LocalName") or v.get("DisplayName") or v["ShortName"],
          "gender": gender.get(v.get("Gender", ""), "")}
         for v in data if v.get("Locale") == "pt-BR"),
        key=lambda v: (v["gender"] != "feminina", v["label"]))
    _voices_cache = (time.monotonic(), f"{region}|{key[-6:]}", voices)
    return voices


class _AzureResponse:
    """Resposta da voz do Azure lida aos poucos (só biblioteca padrão: o Pi não tem httpx)."""

    def __init__(self, text: str, output_format: str) -> None:
        import urllib.error  # noqa: PLC0415
        import urllib.request  # noqa: PLC0415

        key, region, voice = _azure_config()
        ssml = (f"<speak version='1.0' xml:lang='pt-BR'><voice name='{voice}'>"
                f"{_xml_escape(text)}</voice></speak>")
        req = urllib.request.Request(
            f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1", data=ssml.encode("utf-8"),
            method="POST",
            headers={"Ocp-Apim-Subscription-Key": key, "Content-Type": "application/ssml+xml",
                     "X-Microsoft-OutputFormat": output_format, "User-Agent": "cassandra"},
        )
        try:
            self._resp = urllib.request.urlopen(req, timeout=15)
            self.status_code = self._resp.status
            from cassandra import usage_log  # noqa: PLC0415

            usage_log.record_tts("azure", voice, len(text))
        except urllib.error.HTTPError as exc:  # 401 chave errada, 429 franquia/limite, ...
            self._resp = exc
            self.status_code = exc.code
            if exc.code in (401, 403):
                reject_azure_key(key)

    def iter_bytes(self, size: int = 4096) -> Iterator[bytes]:
        while True:
            chunk = self._resp.read(size)
            if not chunk:
                return
            yield chunk

    def read(self) -> bytes:
        return self._resp.read()

    def __enter__(self) -> "_AzureResponse":
        return self

    def __exit__(self, *exc) -> None:
        self._resp.close()


# Chave que o Azure RECUSOU (401/403: errada, apagada ou de um recurso excluído). Tentar de novo a cada 10 min
# atrasava a fala e a conferência do nome a cada tentativa: só volta a tentar quando a chave muda nas Configurações.
_azure_rejected = ""


def azure_key_rejected() -> bool:
    key = _azure_config()[0]
    return bool(key) and key == _azure_rejected


def reject_azure_key(key: str) -> None:
    global _azure_rejected
    if key and key != _azure_rejected:
        _azure_rejected = key
        print("[AZURE] O Azure recusou a chave (401/403): troque em Configurações > Modelo de IA. Até lá, voz e "
              "transcrição vão pela OpenAI.", flush=True)


def _azure_request(text: str, output_format: str) -> _AzureResponse:
    """Abre o streaming da voz do Azure. O chamador lê os bytes enquanto chegam (use com `with`)."""
    return _AzureResponse(text, output_format)

# Variante feminina do espeak-ng. Medido num Raspberry Pi 3: ~80 ms por frase. As alternativas femininas
# grátis foram bem mais lentas (Edge TTS ~4,5 s, Kokoro ~25 s) e o Piper não tem voz feminina em português.
ESPEAK_FEMALE_VARIANT = "f4"
# Voz da OpenAI em streaming: PCM 16-bit mono 24 kHz tocado pelo pw-play enquanto chega (o 1º som sai em ~0,5 s
# com o gpt-4o-mini-tts, contra ~1,8 s esperando o arquivo inteiro).
_STREAM_RATE = 24_000
# Frases curtas (ex.: "Não entendi.", "Pausei.") ficam guardadas: da 2ª vez em diante tocam na hora, sem API.
_TTS_CACHE = Path("data/tts_cache")
# Ganho da voz em dB (VOICE_BOOST_DB no .env; 0 desliga). A fala da OpenAI/Azure sai ~10 dB abaixo de uma música
# (RMS ~-18 dBFS) e, numa caixinha Bluetooth, ficava baixa mesmo no volume máximo. O ganho passa por um limitador
# suave (tanh): a fala sobe e os picos não estouram.
_VOICE_BOOST_DB = float(os.getenv("VOICE_BOOST_DB", "8") or 0)


# Caixas Bluetooth baratas (ex.: a Alaxe) desligam o amplificador no silêncio e só religam ~0,5 s depois que o som
# volta — o começo da frase se perdia ("olá, tudo bem?" saía "tudo bem?"). Antes da fala vai um sopro de ruído
# inaudível (~-60 dBFS) que acorda o amplificador; silêncio puro não serve, a caixa o ignora.
_VOICE_LEAD_MS = float(os.getenv("VOICE_LEAD_MS", "700") or 0)


def _lead_in(rate: int = 24_000) -> bytes:
    """O sopro antes da fala — vazio se o SpeakerWaker já mantém a caixa acordada (aí a fala sai sem esperar)."""
    if speaker_waker.awake():
        return b""
    import numpy as np  # noqa: PLC0415

    return np.random.randint(-30, 31, int(rate * _VOICE_LEAD_MS / 1000), dtype=np.int16).tobytes()


class SpeakerWaker:
    """Mantém o amplificador da caixa acordado (o mesmo sopro inaudível do _lead_in, contínuo) por alguns segundos.

    Chamado quando alguém começa a falar perto do microfone e quando um pedido começa a ser atendido: o bip de
    ativação dura ~0,4 s e a caixa que acorda em ~0,5 s o engolia inteiro — ela ouvia e parecia que não. Com a caixa
    acordada, a resposta também não precisa do sopro antes da fala.

    O bip sai por este mesmo canal (cue): um pw-play novo levava 0,2-1,7 s só para começar a tocar no Pi (medido), e
    o canal já aberto toca o som ~40 ms depois de escrito."""

    RATE = 48_000  # a taxa do PipeWire: sem conversão, e o cano de 4 KB guarda só ~40 ms à frente do que toca
    CHUNK = RATE // 50 * 2  # 20 ms de sopro por vez (bytes)
    LEAD = 0.5  # sopro antes de um som se o canal acabou de abrir (a caixa ainda dormia)
    WARM = 0.8  # canal aberto há tanto tempo: a caixa já acordou
    # Quando o eco do som chega ao microfone depois de escrito: medido no Pi com a Alaxe, 0,58 s (o Bluetooth).
    ECHO_FROM, ECHO_TO = 0.35, 0.6

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._until = 0.0
        self._running = False
        self._since = 0.0  # quando o canal atual abriu
        self._cues: list[bytes] = []  # sons esperando a vez (tocam antes do próximo pedaço de sopro)
        self._sounds: dict[tuple[str, float], bytes] = {}

    def awake(self) -> bool:
        return self._running and time.monotonic() < self._until - 0.3

    def hold(self, seconds: float) -> None:
        if shutil.which("pw-play") is None:
            return
        with self._lock:
            self._until = max(self._until, time.monotonic() + seconds)
            if self._running:
                return
            self._running = True
            self._since = time.monotonic()
        threading.Thread(target=self._run, name="acorda-caixa", daemon=True).start()

    def preload(self, *sounds: tuple[str, float]) -> None:
        """Decodifica os sons (caminho, volume 0-1) uma vez, em segundo plano: o cue toca sem abrir arquivo."""
        def load() -> None:
            for path, volume in sounds:
                pcm = self._decode(path, volume)
                if pcm:
                    self._sounds[(path, volume)] = pcm

        threading.Thread(target=load, name="carrega-sons", daemon=True).start()

    def cue(self, path: str, volume: float = 1.0) -> bool:
        """Toca um som curto (o bip) pelo canal aberto e avisa o microfone de quando o eco dele chega (o eco não é
        voz — speech_state.chiming). False = não dá (sem pw-play, som não carregado): o chamador toca do jeito
        normal."""
        pcm = self._sounds.get((path, volume))
        if not pcm or shutil.which("pw-play") is None:
            return False
        with self._lock:
            warm = self._running and time.monotonic() - self._since >= self.WARM
        lead = b"" if warm else _noise(int(self.RATE * self.LEAD))
        with self._lock:
            self._cues.append(lead + pcm)
        self.hold((len(lead) + len(pcm)) / (2 * self.RATE) + 0.5)
        # canal fechado: o pw-play ainda leva ~0,3 s para abrir, e o sopro vem antes
        start = 0.0 if warm else self.LEAD + 0.3
        speech_state.chiming(start + self.ECHO_FROM, self.ECHO_TO - self.ECHO_FROM + _audible(pcm, self.RATE) + 0.2)
        return True

    def _decode(self, path: str, volume: float) -> bytes:
        """PCM s16 mono a 48 kHz, sem o silêncio do começo do arquivo (o on.mp3 tem ~0,1 s) e com o volume."""
        import numpy as np  # noqa: PLC0415

        if not Path(path).exists() or shutil.which("ffmpeg") is None:
            return b""
        try:
            out = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", path, "-f", "s16le", "-ac", "1",
                                  "-ar", str(self.RATE), "-"], capture_output=True, timeout=30, check=True).stdout
        except (OSError, subprocess.SubprocessError):
            return b""
        x = np.frombuffer(out, dtype=np.int16).astype(np.float32)
        loud = np.nonzero(np.abs(x) > 0.01 * float(np.abs(x).max()))[0] if len(x) else []
        if not len(loud):
            return b""
        x = x[max(0, int(loud[0]) - self.RATE // 200):]  # a partir de 5 ms antes do som
        return np.clip(x * volume, -32768, 32767).astype(np.int16).tobytes()

    def _run(self) -> None:
        proc = None
        try:
            proc = subprocess.Popen(["pw-play", "--raw", "--format", "s16", "--rate", str(self.RATE), "--channels",
                                     "1", "-"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, bufsize=0)
            _shrink_pipe(proc.stdin)
            noise, pos = _noise(self.RATE), 0  # 1 s de sopro, tocado em pedaços
            while True:
                with self._lock:
                    if not self._cues and time.monotonic() >= self._until:
                        self._running = False
                        break
                    data = self._cues.pop(0) if self._cues else None
                if data is None:
                    data, pos = noise[pos:pos + self.CHUNK], (pos + self.CHUNK) % len(noise)
                _write_all(proc.stdin, data)  # bloqueia no ritmo do som
        except (OSError, ValueError):
            with self._lock:
                self._running = False
                self._cues.clear()
        finally:
            if proc is not None:
                try:
                    proc.stdin.close()
                    proc.wait(timeout=3)
                except (OSError, subprocess.TimeoutExpired):
                    proc.kill()


def _audible(pcm: bytes, rate: int) -> float:
    """Segundos até o som cair abaixo de 5% do pico (o on.mp3: ~0,4 s de bip e uma cauda bem mais baixa)."""
    import numpy as np  # noqa: PLC0415

    x = np.abs(np.frombuffer(pcm, dtype=np.int16).astype(np.float32))
    if not len(x):
        return 0.0
    loud = np.nonzero(x > 0.05 * float(x.max()))[0]
    return float(loud[-1] + 1) / rate


def _noise(samples: int) -> bytes:
    """O sopro inaudível (~-60 dBFS) que acorda o amplificador; silêncio puro não serve, a caixa o ignora."""
    import numpy as np  # noqa: PLC0415

    return np.random.randint(-30, 31, samples, dtype=np.int16).tobytes()


def _shrink_pipe(pipe) -> None:
    """Cano de 4 KB (o mínimo do Linux) no lugar de 64 KB: o som escrito toca logo, não depois de ~0,7 s de sopro."""
    try:
        import fcntl  # noqa: PLC0415

        fcntl.fcntl(pipe.fileno(), getattr(fcntl, "F_SETPIPE_SZ", 1031), 4096)
    except (ImportError, OSError):
        pass


def _write_all(pipe, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[pipe.write(view):]


speaker_waker = SpeakerWaker()


class _Booster:
    """Aplica o ganho da voz em PCM 16-bit mono que chega em pedaços (de tamanho qualquer, até ímpar)."""

    def __init__(self, db: float = _VOICE_BOOST_DB) -> None:
        self.gain = 10 ** (db / 20)
        self._rest = b""

    def __call__(self, chunk: bytes) -> bytes:
        if self.gain <= 1.0:
            return chunk
        import numpy as np  # noqa: PLC0415

        data = self._rest + chunk
        cut = len(data) - len(data) % 2
        self._rest = data[cut:]
        x = np.frombuffer(data[:cut], dtype=np.int16).astype(np.float32) / 32768.0
        return (np.tanh(x * self.gain) * 32000).astype(np.int16).tobytes()
_CACHE_MAX_CHARS = 80


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
      - azure: Microsoft Azure Speech (natural pt-BR voices; free tier of 500k chars/month).
      - openai: OpenAI TTS (the most natural; paid; voice "nova" is female).
      - espeak: espeak-ng with a female variant (free, instant, robotic).
      - piper: Piper, neural voice running on the device (free, natural, but male and ~3 s per sentence on
        a Pi 3; only loaded when chosen).
    engine="auto" (default) uses Azure when AZURE_SPEECH_KEY is set, then OpenAI while there's a key and it works; if it fails (e.g. no credits) it
    switches to the female espeak and skips OpenAI for 10 minutes. Every engine falls back to espeak, so a
    missing key or credits never leaves Cassandra silent.

    Playback is always blocking so the microphone is not re-opened
    while Cassandra is still speaking.
    """

    ENGINES = ("auto", "azure", "openai", "piper", "espeak")

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
        self._azure_down_until = 0.0
        self._last_engine: str | None = None
        self._play_lock = threading.Lock()  # uma fala por vez (chat web em segundo plano + microfone)
        self._tl = threading.local()  # geração da fala desta thread: se ela for interrompida, o som para

    # ── API pública ───────────────────────────────────────────────────────────

    def speak(self, text: str) -> None:
        if not self.enabled:
            return
        cleaned = text.strip()
        if not cleaned:
            return
        if speech_state.task_cancelled():
            return  # o pedido que ia falar isto foi interrompido (a pessoa chamou a Cassandra de novo)
        # Enquanto fala (e logo depois), o microfone ignora o que ouve: ela não se ativa com a própria voz.
        with speech_state.speaking(cleaned) as gen:
            self._tl.gen = gen
            if self._speak_streamed(cleaned):
                return
            path = self._synthesize(cleaned)
            if path:
                self._play_file(path)

    # ── Voz da OpenAI em streaming ────────────────────────────────────────────

    def _stopped(self) -> bool:
        """A fala desta thread foi interrompida (a pessoa chamou a Cassandra no meio)?"""
        gen = getattr(self._tl, "gen", None)
        return gen is not None and speech_state.cancelled(gen)

    def _wait_player(self, proc: subprocess.Popen) -> None:
        """Espera o player terminar; se a fala for interrompida, corta o som na hora."""
        while True:
            try:
                proc.wait(timeout=0.05)
                return
            except subprocess.TimeoutExpired:
                if self._stopped():
                    proc.terminate()
                    try:
                        proc.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    return

    def _run_player(self, cmd: list[str], stdin=None) -> None:
        self._wait_player(subprocess.Popen(cmd, stdin=stdin, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

    def _can_stream(self) -> bool:
        """Voz em streaming (Azure ou OpenAI) tocada pelo pw-play enquanto chega."""
        return self._player == "pw-play" and self._engine_order()[0] in ("azure", "openai")

    def _speak_streamed(self, text: str) -> bool:
        """Fala com o 1º motor com streaming que funcionar; False = ninguém conseguiu (quem chamou usa arquivo)."""
        for engine in self._engine_order():
            if engine == "azure" and self._speak_azure_stream(text):
                return True
            if engine == "openai" and self._speak_openai_stream(text):
                return True
            if engine not in ("azure", "openai"):
                return False
        return False

    def _speak_azure_stream(self, text: str) -> bool:
        """Fala `text` com a voz do Azure tocando enquanto chega. False se não deu (a próxima voz assume)."""
        key, _region, voice = _azure_config()
        if (self._player != "pw-play" or not key or time.monotonic() < self._azure_down_until
                or azure_key_rejected()):
            return False
        cache = self._cache_path(text, engine=f"azure|{voice}")
        play = ["pw-play", "--raw", "--format", "s16", "--rate", str(_STREAM_RATE), "--channels", "1", "-"]
        with self._play_lock:
            if cache and cache.exists():
                with tempfile.TemporaryFile() as fh:  # o cache guarda a voz original; o ganho é na hora de tocar
                    fh.write(_lead_in(_STREAM_RATE) + _Booster()(cache.read_bytes()))
                    fh.seek(0)
                    self._run_player(play, stdin=fh)
                usage_log.record_tts("azure", voice, len(text), cached=True)
                return True
            proc = None
            got: list[bytes] = []
            boost = _Booster()
            try:
                with _azure_request(text, "raw-24khz-16bit-mono-pcm") as resp:
                    if resp.status_code != 200:
                        raise RuntimeError(f"HTTP {resp.status_code}: {resp.read()[:160]!r}")
                    for chunk in resp.iter_bytes(4096):
                        if self._stopped():
                            break
                        if proc is None:
                            proc = subprocess.Popen(play, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                                    stderr=subprocess.DEVNULL)
                            proc.stdin.write(_lead_in(_STREAM_RATE))
                            if self._last_engine != "azure":
                                print("[VOZ] Falando com: azure (streaming)", flush=True)
                                self._last_engine = "azure"
                        proc.stdin.write(boost(chunk))
                        if cache:
                            got.append(chunk)
            except Exception as exc:  # noqa: BLE001 — franquia esgotada, rede...: a próxima voz assume
                if proc is None:
                    self._azure_down_until = time.monotonic() + _AZURE_RETRY_AFTER
                    print(f"[VOZ] Voz do Azure falhou ({str(exc)[:160]}); usando a próxima voz por 10 min.",
                          flush=True)
                    return False
            finally:
                if proc is not None:
                    try:
                        proc.stdin.close()
                    except OSError:
                        pass
                    self._wait_player(proc)
            if self._stopped():
                return True
            if proc is None or proc.returncode != 0:
                return False
            if cache and got:
                try:
                    _TTS_CACHE.mkdir(parents=True, exist_ok=True)
                    cache.write_bytes(b"".join(got))
                except OSError:
                    pass
            return True

    def _cache_path(self, text: str, engine: str | None = None) -> Path | None:
        if len(text) > _CACHE_MAX_CHARS:
            return None
        prefix = engine or f"{self.tts_model}|{self.tts_voice}"
        key = hashlib.sha1(f"{prefix}|{text}".encode()).hexdigest()[:20]
        return _TTS_CACHE / f"{key}.pcm"

    def _speak_openai_stream(self, text: str) -> bool:
        """Fala `text` com a voz da OpenAI tocando enquanto ela gera. False se não deu (a voz grátis assume)."""
        if self._player != "pw-play" or self.llm is None or "openai" not in self._engine_order():
            return False
        cache = self._cache_path(text)
        # --raw: sem ele o pw-play (PipeWire 1.4) tenta ler um cabeçalho de arquivo no stdin, recusa o PCM e sai.
        play = ["pw-play", "--raw", "--format", "s16", "--rate", str(_STREAM_RATE), "--channels", "1", "-"]
        with self._play_lock:
            if cache and cache.exists():
                with tempfile.TemporaryFile() as fh:  # o cache guarda a voz original; o ganho é na hora de tocar
                    fh.write(_lead_in(_STREAM_RATE) + _Booster()(cache.read_bytes()))
                    fh.seek(0)
                    self._run_player(play, stdin=fh)
                usage_log.record_tts("openai", self.tts_model, len(text), cached=True)
                return True
            proc = None
            got: list[bytes] = []
            boost = _Booster()
            try:
                stream = self.llm.stream_speech(text, model=self.tts_model, voice=self.tts_voice)
                for chunk in stream:
                    if self._stopped():
                        break
                    if proc is None:
                        proc = subprocess.Popen(play, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                                stderr=subprocess.DEVNULL)
                        proc.stdin.write(_lead_in(_STREAM_RATE))
                        if self._last_engine != "openai":
                            print("[VOZ] Falando com: openai (streaming)", flush=True)
                            self._last_engine = "openai"
                    proc.stdin.write(boost(chunk))
                    if cache:
                        got.append(chunk)
            except Exception as exc:  # noqa: BLE001 — sem créditos, rede...: a voz grátis assume
                if proc is None:
                    self._openai_down_until = time.monotonic() + _OPENAI_RETRY_AFTER
                    print(f"[VOZ] Voz da OpenAI falhou ({str(exc)[:120]}); usando a voz grátis por 10 min.",
                          flush=True)
                    return False
            finally:
                if proc is not None:
                    try:
                        proc.stdin.close()
                    except OSError:
                        pass
                    self._wait_player(proc)
            if self._stopped():
                return True
            if proc is None:
                return False
            if proc.returncode != 0:
                print(f"[VOZ] O pw-play falhou (código {proc.returncode}); tocando por arquivo.", flush=True)
                return False  # não guarda no cache; quem chamou fala de novo pelo caminho de arquivo
            if cache and got:
                try:
                    _TTS_CACHE.mkdir(parents=True, exist_ok=True)
                    cache.write_bytes(b"".join(got))
                except OSError:
                    pass
            return True

    def speak_stream(self, token_iter: Iterator[str]) -> str:
        """Fala a resposta em streaming (ver _speak_stream). Durante a fala e logo depois, o microfone ignora o que
        ouve (speech_state): ela não se ativa nem responde à própria voz."""
        if not self.enabled:
            return "".join(token_iter)
        if speech_state.task_cancelled():
            return ""
        with speech_state.speaking() as gen:
            self._tl.gen = gen
            return self._speak_stream(token_iter)

    def _speak_stream(self, token_iter: Iterator[str]) -> str:
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

        owner = speech_state.task_generation()  # o pedido dono desta resposta (se houver)

        def collect() -> None:
            # Esta thread roda a resposta (LLM, pesquisa, agentes): ela pertence ao mesmo pedido, para esperas e
            # resultados atrasados pararem se a Cassandra for interrompida.
            if owner is not None:
                speech_state.task_begin(owner)
            # Sempre sinaliza o fim (None), mesmo se o LLM falhar no meio (sem crédito, rede...). Sem isso o
            # loop abaixo espera para sempre e trava o assistente inteiro (quem chamou segura o _state_lock).
            try:
                buf = ""
                for token in token_iter:
                    if self._stopped() or speech_state.task_cancelled():
                        break  # interrompida: nem termina de gerar a resposta
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

        if self._can_stream():
            # Voz em streaming: fala cada frase assim que o LLM a termina (o som começa ~0,5 s depois).
            threading.Thread(target=collect, daemon=True).start()
            parts_stream: list[str] = []
            while True:
                sentence = sentence_q.get()
                if sentence is None or self._stopped():
                    break
                parts_stream.append(sentence)
                speech_state.remember(sentence)
                if not self._speak_streamed(sentence):
                    path = self._synthesize(sentence)
                    if path:
                        self._play_file(path)
            if errors:
                raise errors[0]
            return " ".join(parts_stream)

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
            speech_state.remember(sentence)
            if path:
                self._play_file(path)

        if errors:
            raise errors[0]
        return " ".join(parts)

    # ── Síntese ───────────────────────────────────────────────────────────────

    def reset_failures(self) -> None:
        """Chave/voz trocadas nas Configurações: tenta de novo na hora, sem esperar os 10 min de uma falha."""
        self._azure_down_until = 0.0
        self._openai_down_until = 0.0

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
        from cassandra import llm_settings  # noqa: PLC0415

        openai_ok = bool(llm_settings.get()["openai_api_key"]) and time.monotonic() >= self._openai_down_until
        azure_ok = bool(_azure_config()[0]) and time.monotonic() >= self._azure_down_until and not azure_key_rejected()
        if self.engine == "azure":
            # Azure; se ele falhar (ex.: franquia do mês esgotada), a OpenAI segura até ele voltar
            return (["azure"] if azure_ok else []) + (["openai"] if openai_ok else []) + ["espeak"]
        # auto: Azure (se configurado) > OpenAI (se houver chave e não falhou há pouco) > voz feminina grátis
        return (["azure"] if azure_ok else []) + (["openai"] if openai_ok else []) + ["espeak"]

    def _synthesize(self, text: str) -> str | None:
        """Gera o áudio da frase num arquivo temporário (quem toca apaga). None se nenhum motor conseguiu."""
        for engine in self._engine_order():
            try:
                path = getattr(self, f"_synth_{engine}")(text)
            except Exception as exc:  # noqa: BLE001
                if engine == "azure":
                    self._azure_down_until = time.monotonic() + _AZURE_RETRY_AFTER
                    print(f"[VOZ] Voz do Azure falhou ({str(exc)[:120]}); usando a próxima voz por 10 min.", flush=True)
                    continue
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

    def _synth_azure(self, text: str) -> str | None:
        if not _azure_config()[0]:
            return None
        with _azure_request(text, "riff-24khz-16bit-mono-pcm") as resp:
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.read()[:160]!r}")
            audio = resp.read()
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.write(audio)
        tmp.close()
        return tmp.name

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
                    if not self._stopped():
                        self._run_player(cmd)
        finally:
            os.unlink(path)
