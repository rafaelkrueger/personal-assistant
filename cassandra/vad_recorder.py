"""VAD-based audio recorder: captures a complete utterance using energy detection."""
from __future__ import annotations

import math
import os
import struct
import tempfile
import threading
import wave
from collections import deque

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
# Áudio guardado de antes do limite ser cruzado: o começo do nome ("Cas-") é fraco e ficava de fora.
PRE_ROLL_FRAMES = 15  # ~0,45 s


def _is_voiced(frame: bytes) -> bool:
    import numpy as np  # noqa: PLC0415

    x = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
    x = x - x.mean()
    energy = float((x * x).sum())
    if energy < 1e4:
        return False
    ac = np.correlate(x, x, "full")[len(x) - 1:]
    if float(ac[40:201].max() / ac[0]) < VOICED_PERIODICITY:
        return False
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    return float(spec.max() / spec.sum()) < VOICED_MAX_TONAL


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
        pre_roll_frames: int = PRE_ROLL_FRAMES,
    ) -> None:
        self.energy_threshold = energy_threshold
        self.silence_duration = silence_duration
        self.max_duration = max_duration
        self.pre_roll_frames = pre_roll_frames
        self._pa = None
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
        """Abre o microfone na 1ª taxa que ele aceitar. Devolve (stream, taxa, amostras por quadro de 30 ms)."""
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
            self._quiet.append(self._rms(f))
        if len(self._quiet) >= 20:
            ordered = sorted(self._quiet)
            self._noise = ordered[int(len(ordered) * _NOISE_PERCENTILE)]

    @staticmethod
    def _rms(frame: bytes) -> float:
        count = len(frame) // 2
        if not count:
            return 0.0
        shorts = struct.unpack(f"{count}h", frame)
        return math.sqrt(sum(s * s for s in shorts) / count)

    def record_utterance(
        self,
        silence_duration: float | None = None,
        interrupt_event: threading.Event | None = None,
        on_frame=None,
        max_wait: float | None = None,
        min_voiced: int | None = None,
        on_busy_frame=None,
    ) -> str | None:
        """Block until speech is detected, then record until silence.

        Args:
            silence_duration: Override the instance silence_duration for this call.
                Useful for wake-word phase (short) vs command phase (longer).
            interrupt_event: When set by an external thread (e.g. a fired timer),
                recording stops immediately and returns None so the caller can
                handle the interrupt before the next listening window.

        Returns:
            Absolute path to a temporary WAV file containing the utterance,
            or None if no speech was detected or recording was interrupted.
        """
        import pyaudio  # noqa: PLC0415

        pa = self._ensure_pyaudio()
        effective_silence = silence_duration if silence_duration is not None else self.silence_duration
        max_frames = int(self.max_duration * 1000 / FRAME_MS)
        silence_frames_needed = int(effective_silence * 1000 / FRAME_MS)

        # O microfone fica aberto entre uma gravação e outra: o que a pessoa fala logo depois do bip (enquanto o
        # loop troca de gravação) fica guardado e não se perde. Antes ele fechava e reabria a cada fala.
        if getattr(self, "_stream", None) is None:
            self._stream = self._open_stream(pa, pyaudio)
        stream, rate, device_frames = self._stream

        pre_roll: list[bytes] = []
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
        threshold = self._threshold()
        fast_end = False  # quem ouve ao vivo avisou (ex.: o nome foi reconhecido): basta uma pausa curta
        # Nome reconhecido ao vivo: o bip já tocou, mas a gravação segue até o fim da frase ("Cassandra, que horas
        # são?" numa gravação só). Encerrar na 1ª pausa depois do nome picava o pedido em dois e perdia o começo.
        fast_silence_frames = max(silence_frames_needed, int(_AFTER_NAME_SILENCE * 1000 / FRAME_MS))
        waited_frames = 0
        max_wait_frames = int(max_wait * 1000 / FRAME_MS) if max_wait else None

        try:
            for _ in range(max_frames):
                frames_read += 1
                if interrupt_event and interrupt_event.is_set():
                    interrupted = True
                    break

                frame = _to_16k(stream.read(device_frames, exception_on_overflow=False), rate)
                energy = self._rms(frame)
                monitor.level(energy)

                if speech_state.busy():
                    # A Cassandra está falando (ou a caixa ainda toca o fim): o que o microfone ouve é ela mesma.
                    # Nada disso vira pedido — senão ela se ativa sozinha e responde a si mesma em loop. Só o nome
                    # dela interrompe: on_busy_frame procura o nome e, se achar, cancela a fala (speech_state).
                    if speaking:
                        echo_aborted = True
                        break
                    pre_roll.clear()
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
                    self._learn_noise(energy, threshold)
                    threshold = self._threshold()
                    pre_roll.append(frame)
                    if len(pre_roll) > self.pre_roll_frames:
                        pre_roll.pop(0)
                    if energy > threshold:
                        speaking = True
                        if on_frame:
                            for f in pre_roll:
                                fast_end = bool(on_frame(f)) or fast_end
                            fast_end = bool(on_frame(frame)) or fast_end
                        recorded.extend(pre_roll)
                        voiced_frames = sum(_is_voiced(f) for f in pre_roll) + _is_voiced(frame)
                        pre_roll.clear()
                        recorded.append(frame)
                        silent_frames = 0
                        speech_frames = 1
                else:
                    recorded.append(frame)
                    voiced_frames += _is_voiced(frame)
                    if on_frame:
                        fast_end = bool(on_frame(frame)) or fast_end
                    if energy < threshold * SILENCE_RATIO:
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
