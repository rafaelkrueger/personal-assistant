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

    def stream(self) -> "WakeStream | None":
        """Reconhecimento do nome ao vivo, quadro a quadro (ver WakeStream). None se o modelo não carregou."""
        if not self.available():
            return None
        return WakeStream(self)

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
        self.last_heard = result.get("text", "")
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


class WakeStream:
    """Detecta o nome enquanto o áudio chega (30 ms por vez), em vez de esperar a pessoa terminar de falar e a
    gravação inteira: o som de ativação sai quase na hora. Segura o reconhecedor do nome até close()."""

    PARTIAL_EVERY = 2  # checa o parcial a cada ~60 ms

    def __init__(self, speech: LocalSpeech) -> None:
        self.speech = speech
        self.heard = False
        self._texts: list[str] = []
        self._frames = 0
        speech._lock.acquire()
        self._rec = speech._wake_rec
        self._rec.Reset()
        self._open = True

    def _has_name(self, text: str) -> bool:
        words = [w for w in text.split() if w != "[unk]"]
        return any(w in self.speech.wake_words for w in words[:2])

    def feed(self, frame: bytes) -> bool:
        """True só na primeira vez que o nome aparece."""
        if not self._open or self.heard:
            if self._open:
                self._rec.AcceptWaveform(frame)
            return False
        self._frames += 1
        if self._rec.AcceptWaveform(frame):
            text = json.loads(self._rec.Result()).get("text", "")
            self._texts.append(text)
            current = " ".join(self._texts)
        elif self._frames % self.PARTIAL_EVERY == 0:
            current = " ".join([*self._texts, json.loads(self._rec.PartialResult()).get("partial", "")])
        else:
            return False
        if self._has_name(current):
            self.heard = True
            return True
        return False

    def close(self) -> tuple[bool, bool, str]:
        """(ouviu o nome, era só o nome, texto ouvido). Libera o reconhecedor."""
        if not self._open:
            return self.heard, False, " ".join(self._texts)
        try:
            self._texts.append(json.loads(self._rec.FinalResult()).get("text", ""))
        finally:
            self._open = False
            self.speech._lock.release()
        text = " ".join(t for t in self._texts if t).strip()
        heard = self.heard or self._has_name(text)
        words = text.split()
        only_name = heard and bool(words) and all(w in self.speech.wake_words or w == "[unk]" for w in words)
        self.speech.last_only_name = only_name
        self.speech.last_heard = text
        return heard, only_name, text

