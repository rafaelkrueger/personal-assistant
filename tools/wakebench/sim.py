"""Monta a "sala": fala sintética a uma distância (nível + reverberação), o chiado REAL do microfone do Pi e,
opcionalmente, uma TV falando ao fundo. Tudo a 48 kHz, como o microfone USB entrega.
"""
import json
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
RATE = 48_000

# nível RMS (48 kHz) que chega ao microfone e relação som direto/reverberação (dB)
DISTANCES = {
    "perto": (4000.0, 12.0),
    "2-3m": (1600.0, 4.0),
    "sala": (800.0, -1.0),
    "longe": (450.0, -5.0),
}
TV_LEVELS = {"silencio": 0.0, "tv": 450.0, "tv_alta": 800.0}
ENERGY_FLOOR = 400  # VAD_ENERGY_THRESHOLD usado pelo gravador na bancada
NOISE_FILE = "noise48k"  # noise2 = o ruído gravado no Pi às 22h (motor/zumbido em 100-300 Hz)
NOISE_GAIN = 1.0  # 0,5 = sala mais quieta (o ruído medido agora no Pi, com o filtro, é ~100)
LEAD_S = 4.0  # fundo antes da fala (o gravador aprende o ruído)
TAIL_S = 7.0  # fundo depois da fala (dá para ver se a gravação termina)


def load_wav(path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == RATE, path
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float64)


@lru_cache(maxsize=1)
def corpus() -> list[dict]:
    return json.loads((HERE / "corpus.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def noise() -> np.ndarray:
    return load_wav(HERE / "real" / f"{NOISE_FILE}.wav")


def active_rms(x: np.ndarray) -> float:
    fr = x[: len(x) // 1440 * 1440].reshape(-1, 1440)
    r = np.sqrt((fr ** 2).mean(1))
    act = r[r > 0.15 * r.max()]
    return float(np.sqrt((act ** 2).mean())) if len(act) else 1.0


def rir(drr_db: float, rng: np.random.Generator, rt60: float = 0.45) -> np.ndarray:
    n = int(0.6 * RATE)
    t = np.arange(n) / RATE
    tail = rng.standard_normal(n) * np.exp(-6.9 * t / rt60)
    tail[: int(0.003 * RATE)] = 0.0
    tail *= np.sqrt(10 ** (-drr_db / 10) / (tail ** 2).sum())
    tail[0] = 1.0
    return tail


def convolve(x: np.ndarray, h: np.ndarray) -> np.ndarray:
    n = len(x) + len(h) - 1
    size = 1 << (n - 1).bit_length()
    return np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(h, size), size)[:n]


@lru_cache(maxsize=1)
def tv_track() -> np.ndarray:
    rng = np.random.default_rng(7)
    parts = []
    for c in corpus():
        if c["label"] == "tv":
            x = load_wav(HERE / "clips" / f"{c['id']}.wav")
            parts += [convolve(x, rir(-3.0, rng)), np.zeros(int(0.35 * RATE))]
    y = np.concatenate(parts)
    return y / active_rms(y)


def scene(clip_id: str, distance: str, tv: str, seed: int) -> tuple[np.ndarray, dict]:
    """Áudio int16 a 48 kHz e as marcas de tempo (s) da fala: começo, fim do nome, fim da fala."""
    rng = np.random.default_rng(seed)
    meta = next(c for c in corpus() if c["id"] == clip_id)
    level, drr = DISTANCES[distance]
    x = load_wav(HERE / "clips" / f"{clip_id}.wav")
    y = convolve(x, rir(drr, rng))
    y *= level / active_rms(y)
    lead = LEAD_S + rng.uniform(0, 0.4)
    total = int((lead + len(y) / RATE + TAIL_S) * RATE)
    nz = noise()
    reps = int(np.ceil(total / len(nz))) + 1
    start = rng.integers(0, len(nz))
    bg = np.tile(nz, reps)[start:start + total].copy() * NOISE_GAIN
    if TV_LEVELS[tv]:
        track = tv_track()
        off = rng.integers(0, len(track))
        tvx = np.tile(track, int(np.ceil(total / len(track))) + 1)[off:off + total]
        bg += tvx * TV_LEVELS[tv]
    i0 = int(lead * RATE)
    bg[i0:i0 + len(y)] += y
    audio = np.clip(bg, -32768, 32767).astype(np.int16)
    words = meta["words"]
    name_end = next((w["end"] for w in words if "assandra" in w["w"].lower()), None)
    marks = {
        "speech_start": lead + words[0]["start"],
        "name_start": lead + next((w["start"] for w in words if "assandra" in w["w"].lower()), 0.0),
        "name_end": lead + name_end if name_end is not None else None,
        "speech_end": lead + words[-1]["end"],
        "label": meta["label"], "text": meta["text"],
    }
    return audio, marks
