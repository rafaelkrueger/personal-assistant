"""Reconhecimento de voz local (Vosk, offline e gratuito) para o modo microfone.

Dois usos:
  - heard_wake_word(): detecta o nome da assistente numa fala, sem mandar nada para a internet. É o que evita
    transcrever na OpenAI tudo o que se fala perto do microfone — só a fala que começa com o nome segue adiante.
  - transcribe(): transcrição completa local, usada quando não há chave/créditos da OpenAI. Mais lenta
    (alguns segundos por frase num Raspberry Pi 3) e menos precisa que a OpenAI, mas grátis.

Detecção do nome: o Vosk roda com uma gramática restrita (o nome + palavras "concorrentes" parecidas + [unk]).
Sem as concorrentes, frases como "a casa da minha avó" ou "casa da Sandra" viravam "cassandra" (a gramática
força tudo para a única palavra que conhece). Com elas, foram 12/12 acertos nos testes (6 com o nome, 6 sem).
O nome precisa estar entre as 2 primeiras palavras reconhecidas, como no uso normal ("Cassandra, ...").

Modelo: vosk-model-small-pt (~50 MB, baixado sozinho na primeira vez para models/, fora do git).
"""
from __future__ import annotations

import json
import threading
import urllib.request
import wave
import zipfile
from pathlib import Path

DEFAULT_MODEL_PATH = "models/vosk-model-small-pt-0.3"
_MODEL_URL = "https://alphacephei.com/vosk/models/{name}.zip"

# Palavras parecidas com "cassandra" que precisam existir na gramática para não virarem o nome.
_COMPETITORS = ["casa", "da", "sandra", "alessandra", "casada", "cansada"]


class LocalSpeech:
    def __init__(self, wake_words: list[str], model_path: str = DEFAULT_MODEL_PATH, debug: bool = False) -> None:
        self.wake_words = [w.strip().lower() for w in wake_words if w.strip()]
        self.model_path = Path(model_path)
        self.debug = debug
        self._lock = threading.Lock()
        self._model = None
        self._wake_rec = None
        self._ready = threading.Event()
        self._error: Exception | None = None
        # True se a última fala com o nome era só o nome (nada mais reconhecido, nem [unk]).
        self.last_only_name = False

    # ── Carregamento ──────────────────────────────────────────────────────────

    def preload(self) -> None:
        """Carrega o modelo em segundo plano (leva alguns segundos; baixa na primeira vez)."""
        threading.Thread(target=self._load, name="vosk-load", daemon=True).start()

    def _download(self) -> None:
        name = self.model_path.name
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        zip_path = self.model_path.parent / f"{name}.zip"
        print(f"[VOSK] Baixando o modelo de voz local {name} (~50 MB, só na primeira vez)...", flush=True)
        urllib.request.urlretrieve(_MODEL_URL.format(name=name), zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(self.model_path.parent)
        zip_path.unlink(missing_ok=True)

    def _load(self) -> None:
        with self._lock:
            if self._model is not None or self._error is not None:
                return
            try:
                from vosk import KaldiRecognizer, Model, SetLogLevel  # noqa: PLC0415

                SetLogLevel(-1)
                if not self.model_path.exists():
                    self._download()
                self._model = Model(str(self.model_path))
                grammar = self.wake_words + [w for w in _COMPETITORS if w not in self.wake_words] + ["[unk]"]
                self._wake_rec = KaldiRecognizer(self._model, 16000, json.dumps(grammar))
                self._wake_rec.SetWords(True)
                print("[VOSK] Modelo de voz local pronto (detecção do nome sem internet).", flush=True)
            except Exception as exc:  # noqa: BLE001
                self._error = exc
                print(f"[VOSK] Não foi possível carregar o reconhecimento local: {exc}", flush=True)
            finally:
                self._ready.set()

    def available(self) -> bool:
        self._ready.wait(timeout=120)
        return self._model is not None

    # ── Reconhecimento ────────────────────────────────────────────────────────

    @staticmethod
    def _feed(rec, wav_path: str) -> dict:
        with wave.open(wav_path, "rb") as wf:
            while True:
                data = wf.readframes(4000)
                if not data:
                    break
                rec.AcceptWaveform(data)
        return json.loads(rec.FinalResult())

    def heard_wake_word(self, wav_path: str) -> bool:
        if not self.available():
            raise RuntimeError(f"reconhecimento local indisponível: {self._error}")
        with self._lock:
            self._wake_rec.Reset()
            result = self._feed(self._wake_rec, wav_path)
        all_words = [w["word"] for w in result.get("result", [])]
        words = [w for w in all_words if w != "[unk]"]
        heard = any(w in self.wake_words for w in words[:2])
        self.last_only_name = heard and all(w in self.wake_words for w in all_words)
        if self.debug:
            print(f"[WAKE local] {'NOME DETECTADO' if heard else 'sem o nome'} | ouvido: {result.get('text', '')!r}")
        return heard

    def transcribe(self, wav_path: str) -> str:
        if not self.available():
            raise RuntimeError(f"reconhecimento local indisponível: {self._error}")
        from vosk import KaldiRecognizer  # noqa: PLC0415

        with wave.open(wav_path, "rb") as wf:
            rate = wf.getframerate()
        rec = KaldiRecognizer(self._model, rate)  # vocabulário livre; um por chamada (o modelo é compartilhado)
        return (self._feed(rec, wav_path).get("text") or "").strip()

