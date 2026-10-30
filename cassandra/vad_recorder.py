"""VAD-based audio recorder: captures a complete utterance using energy detection."""
from __future__ import annotations

import math
import os
import select
import subprocess
import tempfile
import threading
import time
import wave
from collections import deque
from typing import NamedTuple, Sequence

from cassandra.mic_monitor import monitor
from cassandra import speech_state

SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit PCM
FRAME_MS = 30  # frame duration in milliseconds
FRAME_SIZE = int(SAMPLE_RATE * FRAME_MS / 1000)  # samples per frame = 480
# O limite de fala acompanha o ruído do ambiente: fala = pelo menos NOISE_FACTOR vezes o chiado medido (e nunca
# menos que o VAD_ENERGY_THRESHOLD). Microfones baratos têm um chiado quase no limite fixo; sem isso, trechos de
# puro ruído viram "fala" e a transcrição inventa texto.
NOISE_FACTOR = 2.0
# Menos que isso de fala (quadros acima do limite) não é pedido: é estalo, bip ou ruído — nem vai para transcrever.
MIN_SPEECH_SECONDS = 0.18
# Depois que o nome foi reconhecido ao vivo, esta pausa já encerra a fala (em vez do silêncio normal).
FAST_END_SILENCE = 0.15
# Taxas tentadas ao abrir o microfone. Muitos microfones USB só gravam a 48 kHz: abre na taxa que ele aceita e
# converte para 16 kHz (o que a transcrição e o Vosk esperam).
_CAPTURE_RATES = (16_000, 48_000, 44_100, 32_000, 22_050, 96_000)


# Porta de voz: só é fala se houver som com "tom de voz" — periódico no tom da prega vocal (80–400 Hz) e não um
# tom único (bip). Chiado, estalos e ruído do microfone não passam (0 quadros no ruído real medido), e nada disso
# vai para a transcrição — que, com áudio sem fala, inventa texto.
VOICED_PERIODICITY = 0.45
VOICED_MAX_TONAL = 0.30
# Ruído do ambiente: janela dos últimos ~4,5 s sem fala e o percentil usado como "ruído".
_NOISE_WINDOW = 150
_NOISE_PERCENTILE = 0.2  # o "fundo" do ambiente; a mediana incluía sons baixos da casa e subia demais o limite
# Depois do nome, a pausa que encerra a frase: cobre a vírgula de "Cassandra, que horas são?".
_AFTER_NAME_SILENCE = 0.9
MIN_VOICED_FRAMES = 3  # ~0,2 s de voz
# Histerese: começar a falar exige passar do limite; PARAR exige ficar abaixo de SILENCE_RATIO × limite. Com um
# limite só, a fala fraca (voz de longe) caía abaixo dele no meio da palavra e a gravação acabava ali — o Vosk
# recebia um pedaço do nome e ouvia "nada".
SILENCE_RATIO = 0.7
# Áudio guardado de antes do limite ser cruzado: o começo do nome ("Cas-") é fraco e ficava de fora. Também dá ao
# Vosk um pouco do ambiente antes da fala para ele se ajustar (ele recomeça do zero a cada gravação): medido, de
# longe 52% -> 57% das chamadas reconhecidas com 0,9 s no lugar de 0,45 s.
PRE_ROLL_FRAMES = 30  # ~0,9 s
# Filtro de graves (passa-altas). O "chiado" do microfone USB é quase todo ronco abaixo de 300 Hz (50 Hz e uma
# vibração de ~12 Hz, medidos), onde a voz não tem quase nada: sem ele o ruído cai de ~360 para ~220 RMS e os picos
# pela metade. Com o ronco, o ruído ficava ACIMA do limite de silêncio e a gravação não terminava — ela demorava
# até 30 s para responder e, com a TV ligada, não ouvia o nome. 0 desliga.
HPF_HZ = 100.0
# O filtro também no áudio que vai para o reconhecimento (Vosk e transcrição); False = só na medida de volume.
HPF_FOR_RECOGNITION = True
# O volume que decide "tem fala / acabou a fala" é medido só na faixa da voz (250-4000 Hz): ronco de motor,
# ventilador ou zumbido elétrico (100-300 Hz) e chiado agudo ficam de fora. Medido no Pi: com um ruído desses o
# "silêncio" caiu de 357 para 138 RMS; a voz não perde nada (formantes e quase toda a energia ficam na faixa).
BAND_ENERGY = True
BAND_HZ = (250.0, 4000.0)
# O silêncio que encerra a fala é medido na média dos últimos quadros (~120 ms): um pico solto do ruído não
# recomeça a contagem da pausa.
SILENCE_SMOOTH_FRAMES = 4
# Silêncio também é relativo a QUEM fala: abaixo de REL_SILENCE x o pico da voz da pessoa nesta gravação (~-10 dB)
# conta como pausa. A TV do outro lado da sala é bem mais baixa que a pessoa falando com a Cassandra: sem isso, a
# TV mantinha a gravação aberta e o pedido só era processado segundos depois de a pessoa terminar.
REL_SILENCE = 0.3
# Depois do nome, a gravação dura no máximo isto (o pedido mais longo cabe): com barulho contínuo (TV alta, música)
# ela terminava só nos 30 s do limite geral.
AFTER_NAME_MAX_S = 8.0


class LiveFrame(NamedTuple):
    """O que o gravador sabe do quadro que acabou de passar para o on_frame (VadRecorder.live)."""
    quiet: bool  # conta como pausa (o mesmo critério que encerra a fala)
    voiced: int  # quadros com voz desde o começo da gravação
    peak: float  # pico da voz nesta gravação
    threshold: float  # limite de fala agora
    levels: Sequence[float] = ()  # volume de cada quadro desde que a fala começou
    chime: bool = False  # o quadro caiu no eco do bip dela (speech_state.chime): não conta como voz

    def speech_before(self, quiet_frames: int) -> float:
        """Segundos do primeiro som ALTO da gravação (>= REL_SILENCE x o pico, o mesmo critério da pausa) até onde a
        pausa de quiet_frames quadros começou: a fala de quem chamou, inteira — "eu falei com a Cassandra" conta
        toda —, mas sem a TV mais baixa que já falava antes dela."""
        floor = REL_SILENCE * self.peak
        last = len(self.levels) - quiet_frames - 1
        while last >= 0 and self.levels[last] < floor:  # a pausa é medida na média: os últimos quadros já eram baixos
            last -= 1
        first = next((i for i in range(last + 1) if self.levels[i] >= floor), last + 1)
        return max(0, last - first + 1) * FRAME_MS / 1000


def _is_voiced(frame: bytes) -> bool:
    import numpy as np  # noqa: PLC0415

    x = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
    x = x - x.mean()
    energy = float((x * x).sum())
    if energy < 1e4:
        return False
    # autocorrelação pela FFT (mesmo resultado que np.correlate, ~10x mais leve no Pi): 1024 >= 2 x 480, sem dar a volta
    f = np.fft.rfft(x, 1024)
    ac = np.fft.irfft((f * np.conj(f)).real, 1024)
    if float(ac[40:201].max() / ac[0]) < VOICED_PERIODICITY:
        return False
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    return float(spec.max() / spec.sum()) < VOICED_MAX_TONAL


def _band_rms(frame: bytes) -> float:
    """RMS só da faixa BAND_HZ (pela FFT do quadro com janela Hann — sem ela, o ronco "vaza" para a faixa; mesma
    escala do RMS comum)."""
    import numpy as np  # noqa: PLC0415

    x = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
    n = len(x)
    if not n:
        return 0.0
    window = _hann(n)
    spec = np.fft.rfft(x * window)
    lo, hi = int(BAND_HZ[0] * n / SAMPLE_RATE), int(BAND_HZ[1] * n / SAMPLE_RATE)
    power = float((spec.real[lo:hi] ** 2 + spec.imag[lo:hi] ** 2).sum())
    return math.sqrt(2.0 * power / float(np.mean(window * window))) / n


_HANN: dict[int, object] = {}


def _hann(n: int):
    import numpy as np  # noqa: PLC0415

    if n not in _HANN:
        _HANN[n] = np.hanning(n).astype(np.float32)
    return _HANN[n]


class _HighPass:
    """Passa-altas de 2ª ordem (dois de 1ª ordem em cascata, 12 dB por oitava), contínuo de um quadro para o outro.
    Vetorizado em numpy (o Pi não tem scipy): y[n] = a·y[n-1] + b·(x[n] - x[n-1]), com b = (1 + a) / 2 (ganho 1 na
    faixa da voz), resolvido por soma acumulada."""

    def __init__(self, cutoff: float = HPF_HZ, rate: int = SAMPLE_RATE) -> None:
        self.a = math.exp(-2 * math.pi * cutoff / rate)
        self.b = (1 + self.a) / 2
        self._state = [(0.0, 0.0), (0.0, 0.0)]  # (último x, último y) de cada estágio
        self._powers: dict[int, tuple] = {}

    def __call__(self, frame: bytes) -> bytes:
        import numpy as np  # noqa: PLC0415

        x = np.frombuffer(frame, dtype=np.int16).astype(np.float64)
        if not len(x):
            return frame
        if len(x) not in self._powers:
            k = np.arange(len(x), dtype=np.float64)
            self._powers[len(x)] = (self.a ** k, self.a ** -k)
        pw, inv = self._powers[len(x)]
        for i, (x1, y1) in enumerate(self._state):
            u = self.b * np.diff(x, prepend=x1)
            y = pw * (np.cumsum(inv * u) + self.a * y1)
            self._state[i] = (float(x[-1]), float(y[-1]))
            x = y
        return np.clip(np.rint(x), -32768, 32767).astype(np.int16).tobytes()


def _to_16k(frame: bytes, rate: int) -> bytes:
    """PCM 16-bit mono na taxa do microfone -> 16 kHz."""
    if rate == SAMPLE_RATE:
        return frame
    import numpy as np  # noqa: PLC0415

    samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
    if rate % SAMPLE_RATE == 0:  # 48 kHz, 32 kHz...: média de cada grupo (filtro passa-baixa simples)
        factor = rate // SAMPLE_RATE
        samples = samples[: len(samples) // factor * factor].reshape(-1, factor).mean(axis=1)
    else:
        target = int(round(len(samples) * SAMPLE_RATE / rate))
        samples = np.interp(np.linspace(0, len(samples) - 1, target), np.arange(len(samples)), samples)
    return np.clip(samples, -32768, 32767).astype(np.int16).tobytes()


def bluetooth_mic() -> str | None:
    """A entrada Bluetooth (viva-voz) que o microfone deve usar agora, ex. "bluez_input.41:42:9B:1E:A8:01"; None =
    microfone USB. Segue a escolha da aba Aparelhos (cassandra/audio_routes.py).

    O WirePlumber cria essa entrada para todo aparelho com perfil viva-voz e troca o aparelho para esse perfil
    sozinho enquanto alguém grava dela (o som cai para qualidade de telefone, 16 kHz mono, nos dois sentidos).
    """
    from cassandra.audio_routes import bluetooth_mic_input  # noqa: PLC0415

    return bluetooth_mic_input()


class _PipeWireStream:
    """Microfone lido pelo pw-record, no lugar do PyAudio: o PyAudio só enxerga os microfones do ALSA (USB), e os
    Bluetooth só existem no PipeWire. Mesma interface que o PyAudio usa aqui (read/stop_stream/close)."""

    def __init__(self, target: str) -> None:
        self.target = target
        self._proc = subprocess.Popen(
            ["pw-record", "--target", target, "--rate", str(SAMPLE_RATE), "--channels", str(CHANNELS),
             "--format", "s16", "--raw", "--latency", f"{FRAME_MS}ms", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        self._fd = self._proc.stdout.fileno()

    def read(self, frames: int, exception_on_overflow: bool = False) -> bytes:  # noqa: ARG002
        size = frames * SAMPLE_WIDTH
        data = b""
        while len(data) < size:
            # a caixa desligou/saiu do alcance: sem isso a leitura travaria a Cassandra para sempre. Folga de 10 s:
            # a troca para o perfil viva-voz leva alguns segundos, e desistir antes fazia a caixa ficar trocando de
            # perfil até perder o áudio.
            ready, _, _ = select.select([self._fd], [], [], 10.0)
            chunk = os.read(self._fd, size - len(data)) if ready else b""
            if not chunk:
                raise OSError(f"o microfone Bluetooth parou ({self.target})")
            data += chunk
        return data

    def stop_stream(self) -> None:
        pass

    def close(self) -> None:
        self._proc.terminate()
        try:
            self._proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        self._proc.stdout.close()


# Quanto áudio a fila do microfone guarda (se o processamento ficar para trás, o mais velho sai).
_CAPTURE_QUEUE_SECONDS = 20.0


class _CaptureThread:
    """Lê o microfone numa thread só para isso e guarda o áudio numa fila.

    O microfone USB tem só ~30 ms de buffer (medido no Pi): qualquer pausa maior do laço que processa o áudio — o
    Vosk digerindo o começo da fala, o coletor de lixo, outra thread — perdia som, e o começo da fala é justamente o
    nome. Cada quadro leva a marca de se a Cassandra estava falando NA HORA da captura (speech_state.busy()): a fila
    pode ser processada um pouco depois, e a voz dela nunca pode virar pedido."""

    def __init__(self, stream, frames: int) -> None:
        import queue  # noqa: PLC0415

        self.stream = stream  # PyAudio ou _PipeWireStream
        self.target = getattr(stream, "target", None)
        self._frames = frames
        self._queue = queue.Queue(maxsize=max(1, int(_CAPTURE_QUEUE_SECONDS * 1000 / FRAME_MS)))
        self._stop = threading.Event()
        self._error: Exception | None = None
        self._thread = threading.Thread(target=self._run, name="microfone", daemon=True)
        self._thread.start()

    def _put(self, item) -> None:
        import queue  # noqa: PLC0415

        try:
            self._queue.put_nowait(item)
        except queue.Full:  # o processamento ficou muito para trás: o áudio mais velho sai
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            self._queue.put_nowait(item)

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                data = self.stream.read(self._frames, exception_on_overflow=False)
                self._put((data, speech_state.busy(), speech_state.chime()))
        except Exception as exc:  # noqa: BLE001 — microfone desplugado, caixa Bluetooth desligou...
            self._error = exc
        finally:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:  # noqa: BLE001
                pass
            self._put(None)  # acorda quem espera um quadro

    def read_frame(self, timeout: float = 15.0) -> tuple[bytes, bool, bool]:
        """(áudio, ela estava falando na hora, era o eco do bip dela). OSError se o microfone parou."""
        import queue  # noqa: PLC0415

        try:
            item = self._queue.get(timeout=timeout)
        except queue.Empty as exc:
            raise OSError("o microfone parou de mandar áudio") from exc
        if item is None:
            self._put(None)  # quem ler de novo também vê o fim
            raise OSError(f"o microfone parou: {self._error}")
        return item

    def stop_stream(self) -> None:
        pass

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)  # a própria thread fecha o aparelho (fechar daqui, no meio de um read, não é seguro)


class VadRecorder:
    """Records audio continuously, returning one complete utterance per call.

    Uses energy-based Voice Activity Detection:
    - Waits for audio energy to exceed `energy_threshold` (speech start)
    - Records until energy stays below threshold for `silence_duration` seconds
    - Keeps a short pre-roll buffer so the beginning of speech is never clipped
    - Stops unconditionally after `max_duration` seconds

    Args:
        energy_threshold: RMS energy level that distinguishes speech from silence.
            Typical ambient noise is 50-200; speech is 500-5000+. Tune via MIC_DEBUG.
        silence_duration: Seconds of sustained silence required to end recording.
        max_duration: Hard cap on recording length in seconds.
        pre_roll_frames: Number of 30ms frames to keep before speech onset (~450ms).
    """

    def __init__(
        self,
        energy_threshold: int = 400,
        silence_duration: float = 1.2,
        max_duration: float = 30.0,
        pre_roll_frames: int | None = None,
    ) -> None:
        self.energy_threshold = energy_threshold
        self.silence_duration = silence_duration
        self.max_duration = max_duration
        self.pre_roll_frames = pre_roll_frames or PRE_ROLL_FRAMES
        self._pa = None
        self._source_checked = 0.0  # última vez que conferiu se apareceu/sumiu um microfone Bluetooth
        self._source_misses = 0  # conferências seguidas em que o microfone certo era outro
        self._opened_choice = ""  # a escolha da aba Aparelhos quando o microfone atual foi aberto
        monitor.set(threshold=energy_threshold)
        self._rate: int | None = None  # a taxa que o microfone atual aceitou
        self._noise: float | None = None  # ruído do ambiente (percentil baixo da energia recente sem fala)
        self._quiet: deque[float] = deque(maxlen=_NOISE_WINDOW)  # energia dos últimos quadros sem fala

    def _ensure_pyaudio(self):
        if self._pa is None:
            try:
                import pyaudio  # noqa: PLC0415
            except ImportError as exc:
                raise RuntimeError(
                    "pyaudio nao instalado. Execute: pip install pyaudio"
                ) from exc
            self._pa = pyaudio.PyAudio()
        return self._pa

    @staticmethod
    def _input_device(pa) -> int | None:
        """Prefere a entrada do PipeWire/Pulse (converte a taxa e segue o microfone padrão, inclusive um recém
        plugado — precisa do pacote pipewire-alsa); senão, o primeiro aparelho de hardware com entrada."""
        devices = [pa.get_device_info_by_index(i) for i in range(pa.get_device_count())]
        inputs = [d for d in devices if d.get("maxInputChannels", 0) > 0]
        for name in ("pipewire", "pulse", "default"):
            for d in inputs:
                if d.get("name") == name:
                    return int(d["index"])
        return int(inputs[0]["index"]) if inputs else None

    def _open_stream(self, pa, pyaudio):
        """Abre o microfone na 1ª taxa que ele aceitar. Devolve (stream, taxa, amostras por quadro de 30 ms).
        Um microfone Bluetooth conectado (viva-voz) tem preferência sobre o USB."""
        from cassandra.audio_routes import mic_choice  # noqa: PLC0415

        self._source_checked = time.time()
        self._opened_choice = mic_choice()
        bt = bluetooth_mic()
        if bt:
            stream = _PipeWireStream(bt)
            if self._rate != -1:
                print(f"[MIC] Microfone Bluetooth aberto: {bt}", flush=True)
                monitor.set(device=bt, rate=SAMPLE_RATE)
                monitor.event("status", f"Microfone aberto: Bluetooth ({bt.split('.', 1)[-1]})")
            self._rate = -1  # marca "Bluetooth": ao voltar para o USB, a taxa dele é descoberta de novo
            return stream, SAMPLE_RATE, FRAME_SIZE
        if self._rate == -1:
            self._rate = None
        device = self._input_device(pa)
        rates = list(_CAPTURE_RATES)
        if device is not None:
            default = int(pa.get_device_info_by_index(device).get("defaultSampleRate") or 0)
            if default:
                rates.append(default)
        if self._rate:
            rates.insert(0, self._rate)
        last_error: Exception | None = None
        for rate in dict.fromkeys(rates):
            frames = int(rate * FRAME_MS / 1000)
            try:
                stream = pa.open(format=pyaudio.paInt16, channels=CHANNELS, rate=rate, input=True,
                                 input_device_index=device, frames_per_buffer=frames)
            except Exception as exc:  # noqa: BLE001 — "Invalid sample rate" e afins: tenta a próxima
                last_error = exc
                continue
            if rate != self._rate:
                note = "" if rate == SAMPLE_RATE else f" (convertido para {SAMPLE_RATE} Hz)"
                print(f"[MIC] Microfone aberto a {rate} Hz{note}", flush=True)
                try:
                    name = pa.get_device_info_by_index(device).get("name", "") if device is not None else ""
                except Exception:  # noqa: BLE001
                    name = ""
                monitor.set(device=name, rate=rate)
                monitor.event("status", f"Microfone aberto: {name or 'padrão'} a {rate} Hz{note}")
            self._rate = rate
            return stream, rate, frames
        raise last_error or RuntimeError("nenhum microfone")

    def _threshold(self) -> float:
        noise = self._noise or 0.0
        value = max(float(self.energy_threshold), noise * NOISE_FACTOR)
        monitor.set(threshold=round(value), noise=round(noise))
        return value

    def _learn_noise(self, energy: float, threshold: float) -> None:
        """Ruído do ambiente = percentil baixo da energia dos últimos segundos sem fala. Acompanha o ambiente
        para cima e para baixo (antes era uma média que só aceitava valores perto do ruído antigo: se o ambiente
        ficava mais alto, o limite nunca subia e qualquer barulho virava uma "fala" de 30 s)."""
        self._quiet.append(energy)
        if len(self._quiet) >= 20:
            ordered = sorted(self._quiet)
            self._noise = ordered[int(len(ordered) * _NOISE_PERCENTILE)]
        elif self._noise is None and energy < threshold:
            self._noise = energy

    def _absorb_as_noise(self, frames: list[bytes]) -> None:
        """Uma "fala" descartada (ou que nunca terminava) era ruído: entra na medida do ambiente, e o limite sobe
        na hora — senão o mesmo barulho dispara gravações inúteis de novo e de novo."""
        for f in frames[-_NOISE_WINDOW:]:
            self._quiet.append(self._energy(f))
        if len(self._quiet) >= 20:
            ordered = sorted(self._quiet)
            self._noise = ordered[int(len(ordered) * _NOISE_PERCENTILE)]

    @staticmethod
    def _energy(frame: bytes) -> float:
        """O volume que o VAD usa (ver BAND_ENERGY)."""
        return _band_rms(frame) if BAND_ENERGY else VadRecorder._rms(frame)

    @staticmethod
    def _rms(frame: bytes) -> float:
        import numpy as np  # noqa: PLC0415

        x = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        return float(np.sqrt(np.mean(x * x))) if len(x) else 0.0

    def record_utterance(
        self,
        silence_duration: float | None = None,
        interrupt_event: threading.Event | None = None,
        on_frame=None,
        max_wait: float | None = None,
        min_voiced: int | None = None,
        on_busy_frame=None,
        min_level: float | None = None,
    ) -> str | None:
        """Block until speech is detected, then record until silence.

        Args:
            silence_duration: Override the instance silence_duration for this call.
                Useful for wake-word phase (short) vs command phase (longer).
            interrupt_event: When set by an external thread (e.g. a fired timer),
                recording stops immediately and returns None so the caller can
                handle the interrupt before the next listening window.
            min_level: volume mínimo da fala (RMS) — depois do nome, o pedido vem da mesma pessoa, com uma voz
                parecida com a do chamado; som bem mais baixo que isso (a TV do outro lado da sala) não abre gravação
                nem vira pedido. last_peak guarda o pico da voz de cada gravação.

        Returns:
            Absolute path to a temporary WAV file containing the utterance,
            or None if no speech was detected or recording was interrupted.
        """
        import pyaudio  # noqa: PLC0415

        pa = self._ensure_pyaudio()
        effective_silence = silence_duration if silence_duration is not None else self.silence_duration
        max_frames = int(self.max_duration * 1000 / FRAME_MS)
        silence_frames_needed = int(effective_silence * 1000 / FRAME_MS)

        # O microfone fica aberto entre uma gravação e outra, lido sem parar pela _CaptureThread: o que a pessoa fala
        # logo depois do bip (enquanto o loop transcreve e troca de gravação) fica na fila e não se perde.
        from cassandra.audio_routes import mic_choice  # noqa: PLC0415

        if getattr(self, "_stream", None) is not None and mic_choice() != self._opened_choice:
            self._close_stream()  # a escolha mudou na aba Aparelhos: troca já, sem a folga abaixo
        if getattr(self, "_stream", None) is not None and time.time() - self._source_checked > 10:
            # um microfone Bluetooth conectou ou desconectou: troca de microfone — só depois de 3 conferências
            # seguidas (~30 s), porque a entrada Bluetooth some por instantes quando a caixa troca de perfil
            self._source_checked = time.time()
            current = getattr(self._stream[0], "target", None)
            self._source_misses = self._source_misses + 1 if bluetooth_mic() != current else 0
            if self._source_misses >= 3:
                self._source_misses = 0
                self._close_stream()
        if getattr(self, "_stream", None) is None:
            opened, opened_rate, opened_frames = self._open_stream(pa, pyaudio)
            self._stream = (_CaptureThread(opened, opened_frames), opened_rate, opened_frames)
        stream, rate, device_frames = self._stream
        if isinstance(stream, _CaptureThread):
            read_frame = stream.read_frame
        else:  # stream de teste (lido direto, sem a thread)
            def read_frame():
                return stream.read(device_frames, exception_on_overflow=False), speech_state.busy(), speech_state.chime()
        if getattr(self, "_hpf", None) is None and HPF_HZ:
            self._hpf = _HighPass(HPF_HZ)
        hpf = self._hpf if HPF_HZ else None
        recent: deque[float] = deque(maxlen=max(1, SILENCE_SMOOTH_FRAMES))  # energia dos últimos quadros

        pre_roll: list[bytes] = []
        pre_chime: list[bool] = []  # quais quadros do pre_roll eram o eco do bip
        recorded: list[bytes] = []
        speaking = False
        silent_frames = 0
        speech_frames = 0
        voiced_frames = 0
        interrupted = False
        echo_aborted = False  # ela começou a falar no meio da gravação
        barged = False  # alguém disse o nome enquanto ela falava: esta gravação é o pedido novo
        frames_read = 0
        busy_tail: list[bytes] = []  # ~1,5 s de áudio da fala dela, para a gravação incluir o nome dito por cima
        self.last_barged = False
        self.last_peak = 0.0
        self.live = None
        threshold = self._threshold()
        fast_end = False  # quem ouve ao vivo avisou (ex.: o nome foi reconhecido): basta uma pausa curta
        # Nome reconhecido ao vivo: o bip já tocou, mas a gravação segue até o fim da frase ("Cassandra, que horas
        # são?" numa gravação só). Encerrar na 1ª pausa depois do nome picava o pedido em dois e perdia o começo.
        fast_silence_frames = max(silence_frames_needed, int(_AFTER_NAME_SILENCE * 1000 / FRAME_MS))
        fast_end_at: int | None = None  # quadro em que o nome foi reconhecido
        after_name_frames = int(AFTER_NAME_MAX_S * 1000 / FRAME_MS)
        peak = 0.0  # pico (suavizado) da voz de quem fala nesta gravação
        levels: list[float] = []  # volume de cada quadro desde que a fala começou (LiveFrame.speech_before)
        waited_frames = 0
        max_wait_frames = int(max_wait * 1000 / FRAME_MS) if max_wait else None

        try:
            for _ in range(max_frames):
                frames_read += 1
                if interrupt_event and interrupt_event.is_set():
                    interrupted = True
                    break

                data, busy, chime = read_frame()
                raw = _to_16k(data, rate)
                clean = hpf(raw) if hpf is not None else raw
                frame = clean if HPF_FOR_RECOGNITION else raw  # o que vai para o Vosk, a gravação e a transcrição
                energy = _band_rms(raw) if BAND_ENERGY else self._rms(clean)
                recent.append(energy)
                monitor.level(energy)

                if busy:
                    # A Cassandra está falando (ou a caixa ainda toca o fim): o que o microfone ouve é ela mesma.
                    # Nada disso vira pedido — senão ela se ativa sozinha e responde a si mesma em loop. Só o nome
                    # dela interrompe: on_busy_frame procura o nome e, se achar, cancela a fala (speech_state).
                    if speaking:
                        echo_aborted = True
                        break
                    pre_roll.clear()
                    pre_chime.clear()
                    busy_tail.append(frame)
                    if len(busy_tail) > 50:
                        busy_tail.pop(0)
                    if on_busy_frame and on_busy_frame(frame):
                        # Interrompida: a gravação começa aqui, já com o nome, e segue até a pessoa parar de falar.
                        barged = True
                        speaking = True
                        recorded.extend(busy_tail)
                        busy_tail.clear()
                        silent_frames = 0
                        speech_frames = voiced_frames = MIN_VOICED_FRAMES
                    continue  # também não conta no prazo de espera nem ensina o "ruído de fundo"
                busy_tail.clear()

                if not speaking:
                    waited_frames += 1
                    if max_wait_frames and waited_frames > max_wait_frames:
                        break  # ninguém falou dentro do prazo
                    if not chime:  # o eco do bip não é o ambiente
                        self._learn_noise(energy, threshold)
                        threshold = self._threshold()
                    pre_roll.append(frame)
                    pre_chime.append(chime)
                    if len(pre_roll) > self.pre_roll_frames:
                        pre_roll.pop(0)
                        pre_chime.pop(0)
                    if energy > max(threshold, min_level or 0.0):
                        speaking = True
                        # o eco do bip pode abrir a gravação (alguém pode falar logo depois), mas nunca conta como voz
                        voiced_frames = (sum(_is_voiced(f) for f, c in zip(pre_roll, pre_chime) if not c)
                                         + (not chime and _is_voiced(frame)))
                        levels.append(energy)
                        self.live = LiveFrame(False, voiced_frames, 0.0, threshold, levels, chime)
                        if on_frame:
                            for f, c in zip(pre_roll, pre_chime):
                                self.live = LiveFrame(False, voiced_frames, 0.0, threshold, levels, c)
                                fast_end = bool(on_frame(f)) or fast_end
                            self.live = LiveFrame(False, voiced_frames, 0.0, threshold, levels, chime)
                            fast_end = bool(on_frame(frame)) or fast_end
                        recorded.extend(pre_roll)
                        pre_roll.clear()
                        pre_chime.clear()
                        recorded.append(frame)
                        silent_frames = 0
                        speech_frames = 1
                else:
                    recorded.append(frame)
                    voiced = not chime and _is_voiced(clean)
                    voiced_frames += voiced
                    smooth = math.sqrt(sum(e * e for e in recent) / len(recent))
                    if voiced:
                        peak = max(peak, smooth)
                    quiet = smooth < max(threshold * SILENCE_RATIO, REL_SILENCE * peak)
                    levels.append(energy)
                    self.live = LiveFrame(quiet, voiced_frames, peak, threshold, levels, chime)
                    if on_frame:
                        fast_end = bool(on_frame(frame)) or fast_end
                    if fast_end and fast_end_at is None:
                        fast_end_at = frames_read
                    if fast_end_at is not None and frames_read - fast_end_at >= after_name_frames:
                        break  # barulho contínuo depois do nome: o pedido já cabia aqui
                    if quiet:
                        silent_frames += 1
                        if silent_frames >= (fast_silence_frames if fast_end else silence_frames_needed):
                            break
                    else:
                        silent_frames = 0
                    if energy >= threshold * 0.8:  # sílabas mais fracas contam; o chiado (bem abaixo) não
                        speech_frames += 1
        except Exception:
            self._close_stream()  # microfone desplugado etc.: reabre na próxima
            raise

        if interrupted or echo_aborted:
            return None

        if not recorded:
            return None
        if frames_read >= max_frames and not barged and not fast_end:
            # 30 s sem parar de "falar": era barulho do ambiente, não alguém falando.
            print(f"[VAD] descartado: som contínuo por {self.max_duration:.0f} s (ruído do ambiente)", flush=True)
            self._absorb_as_noise(recorded)
            return None
        speech_seconds = speech_frames * FRAME_MS / 1000
        # Se o nome já foi reconhecido ao vivo (o bip já tocou), a fala é de verdade: nunca descarta.
        self.last_barged = barged
        self.last_peak = peak
        if min_level and not fast_end and not barged and peak < min_level:
            print(f"[VAD] descartado: voz {peak:.0f} bem mais baixa que a de quem chamou ({min_level:.0f})", flush=True)
            return None
        if not fast_end and not barged:
            needed = MIN_VOICED_FRAMES if min_voiced is None else min_voiced
            if speech_seconds < MIN_SPEECH_SECONDS or voiced_frames < needed:
                # estalo/chiado/bip: nem vai para a transcrição. Só no log do serviço (não na aba Microfone),
                # para dar para calibrar os limites.
                print(f"[VAD] descartado: fala {speech_seconds:.2f} s, voz {voiced_frames}/{needed} quadros, "
                      f"limite {threshold:.0f}", flush=True)
                return None

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        with wave.open(tmp.name, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(SAMPLE_WIDTH)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(b"".join(recorded))

        return tmp.name

    def _close_stream(self) -> None:
        self._hpf = None  # microfone novo: o filtro recomeça do zero
        opened, self._stream = getattr(self, "_stream", None), None
        if opened is not None:
            try:
                opened[0].stop_stream()
                opened[0].close()
            except Exception:  # noqa: BLE001
                pass

    def close(self) -> None:
        self._close_stream()
        self._rate = None  # outro microfone pode ser plugado: descobre a taxa de novo
        if self._pa is not None:
            self._pa.terminate()
            self._pa = None
