"""Voz local com o Piper (neural, offline e gratuita) — a alternativa sem créditos à voz da OpenAI.

Voz padrão: pt_BR-faber-medium (~63 MB, baixada sozinha na primeira vez para models/piper/, fora do git).
Num Raspberry Pi 3 carrega em ~16 s (feito em segundo plano no start) e gera a fala ~1,5x mais devagar que o
tempo real (frase curta ~3 s). A voz pt_BR-edresson-low não foi mais rápida e erra os sons nasais (ã, õ).
"""
from __future__ import annotations

import tempfile
import threading
import urllib.request
import wave
from pathlib import Path

DEFAULT_VOICE = "models/piper/pt_BR-faber-medium.onnx"
_VOICE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/{speaker}/{quality}/{file}?download=true"


class PiperTTS:
    def __init__(self, model_path: str = DEFAULT_VOICE) -> None:
        self.model_path = Path(model_path)
        self._voice = None
        self._error: Exception | None = None
        self._lock = threading.Lock()
        self._ready = threading.Event()

    def preload(self) -> None:
        threading.Thread(target=self._load, name="piper-load", daemon=True).start()

    def _download(self) -> None:
        # nome no padrão do repositório de vozes: <lang>-<speaker>-<quality>.onnx
        _lang, speaker, quality = self.model_path.stem.split("-", 2)
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"[VOZ] Baixando a voz local {self.model_path.name} (~63 MB, só na primeira vez)...", flush=True)
        for file in (self.model_path.name, self.model_path.name + ".json"):
            url = _VOICE_URL.format(speaker=speaker, quality=quality, file=file)
            urllib.request.urlretrieve(url, self.model_path.parent / file)

    def _load(self) -> None:
        with self._lock:
            if self._voice is not None or self._error is not None:
                return
            try:
                from piper import PiperVoice  # noqa: PLC0415

                if not self.model_path.exists():
                    self._download()
                self._voice = PiperVoice.load(str(self.model_path))
                print(f"[VOZ] Voz local (Piper) pronta: {self.model_path.stem}", flush=True)
            except Exception as exc:  # noqa: BLE001
                self._error = exc
                print(f"[VOZ] Piper indisponível: {exc}", flush=True)
            finally:
                self._ready.set()

    def available(self, wait: float = 60) -> bool:
        if not self._ready.is_set():
            self.preload()  # idempotente: se já está carregando, a thread nova só espera e sai
        self._ready.wait(timeout=wait)
        return self._voice is not None

    def synthesize_to_file(self, text: str, rate_wpm: int = 160) -> str:
        """Gera um WAV temporário e devolve o caminho (quem chama apaga). rate_wpm: 160 = velocidade normal."""
        if not self.available():
            raise RuntimeError(f"Piper indisponível: {self._error}")
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        length_scale = max(0.5, min(2.0, 160 / max(80, rate_wpm)))  # maior = mais devagar
        with self._lock, wave.open(tmp.name, "wb") as wf:
            try:
                from piper import SynthesisConfig  # noqa: PLC0415

                self._voice.synthesize_wav(text, wf, syn_config=SynthesisConfig(length_scale=length_scale))
            except ImportError:
                self._voice.synthesize_wav(text, wf)
        return tmp.name
