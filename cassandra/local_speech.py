"""Reconhecimento de voz local (Vosk, offline e gratuito) para o modo microfone.

Dois usos:
  - heard_wake_word(): detecta o nome da assistente numa fala, sem mandar nada para a internet. É o que evita
    transcrever na OpenAI tudo o que se fala perto do microfone — só a fala que começa com o nome segue adiante.
  - transcribe(): transcrição completa local, usada quando não há chave/créditos da OpenAI. Mais lenta
    (alguns segundos por frase num Raspberry Pi 3) e menos precisa que a OpenAI, mas grátis.

Detecção do nome: o Vosk roda com uma gramática restrita (o nome e as variações — "sandra", "alessandra"…,
ver CASSANDRA_VARIANTS em config.py — + palavras "concorrentes" parecidas + [unk]). Sem as concorrentes, frases
como "a casa da minha avó" viravam "cassandra" (a gramática força tudo para a única palavra que conhece).
O nome precisa estar entre as 2 primeiras palavras reconhecidas, como no uso normal ("Cassandra, ...") — por
isso "casa da Sandra" não chama, mas "Sandra, ..." chama.

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

# Palavras parecidas com "cassandra" que precisam existir na gramática para não virarem o nome (todas existem
# no vocabulário do modelo pequeno; palavras fora dele são ignoradas pelo Vosk). Mais concorrentes = menos falas
# da casa viram "candidato a nome" (cada candidato custa uma transcrição para conferir).
_COMPETITORS = ["casa", "da", "casada", "cansada", "cansado", "cansa", "passa", "sandro", "alexandre", "alessandro",
                "varanda", "lasanha", "banda", "manda", "mandar", "anda", "andar", "canta", "cassino", "candidata",
                "agenda", "fazenda", "saudade", "senhora", "nada", "ainda", "vamos", "assim", "sabe", "sala"]
_BARGE_LOCK = threading.Lock()  # cria o detector de interrupção uma vez só (ver barge_detector)

# Concorrentes que, como 1ª palavra, costumam ser o próprio nome mal ouvido de longe ("Sandro, ..." no lugar de
# "Cassandra, ..."). Viram só CANDIDATO: a transcrição confirma e "Sandro, vem jantar" é descartado lá.
_NEAR_NAME_FIRST = {"sandro"}
# Variações curtas do nome: valem no começo de uma gravação, mas NUNCA no meio de outra fala ("Sandra, vem cá"
# numa novela) — lá só o nome inteiro.
_SHORT_NAMES = {"sandra", "alessandra", "lessandra"}  # medido: "alessandro" não resgatava nenhuma chamada e só gerava conferências

# Ganho antes do Vosk. O modelo pequeno trata fala baixa (voz do outro lado da sala num microfone USB barato, RMS
# ~500-800 com chiado ~270) como silêncio e devolve texto VAZIO — medido: longe, 12% das chamadas reconhecidas.
# O ganho acompanha o nível da própria fala (ataque imediato, sem soltar dentro da gravação): fala baixa sobe até
# AGC_MAX_GAIN vezes, fala perto fica quase igual. Só o que vai para o Vosk; a gravação guardada não muda.
AGC_TARGET_RMS = 3500.0
AGC_MAX_GAIN = 5.0


class _Agc:
    def __init__(self) -> None:
        self.level = 0.0

    def reset(self) -> None:
        self.level = 0.0

    def __call__(self, frame: bytes) -> bytes:
        import numpy as np  # noqa: PLC0415

        x = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        if not len(x):
            return frame
        rms = float(np.sqrt(np.mean(x * x)))
        self.level = max(self.level, rms)
        gain = min(AGC_MAX_GAIN, max(1.0, AGC_TARGET_RMS / max(self.level, 1.0)))
        if gain == 1.0:
            return frame
        y = x * gain
        # Limitador suave em vez de cortar o pico (corte vira chiado e atrapalha o reconhecedor).
        y = np.tanh(y / 32768.0) * 32767.0
        return y.astype(np.int16).tobytes()


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
    def _feed(rec, wav_path: str, agc: "_Agc | None" = None) -> dict:
        with wave.open(wav_path, "rb") as wf:
            while True:
                data = wf.readframes(480)
                if not data:
                    break
                rec.AcceptWaveform(agc(data) if agc else data)
        return json.loads(rec.FinalResult())

    def has_name(self, words: list[str]) -> bool:
        """O nome (ou um concorrente que costuma ser ele mal ouvido) entre as 2 primeiras palavras reconhecidas."""
        words = [w for w in words if w != "[unk]"]
        return any(w in self.wake_words for w in words[:2]) or (bool(words) and words[0] in _NEAR_NAME_FIRST)

    def stream(self) -> "WakeStream | None":
        """Reconhecimento do nome ao vivo, quadro a quadro (ver WakeStream). None se o modelo não carregou."""
        if not self.available():
            return None
        return WakeStream(self)

    def barge_detector(self) -> "BargeDetector | None":
        """Detector do nome enquanto a Cassandra fala (interromper). None se o modelo não carregou."""
        if not self.available():
            return None
        # Trava própria: a self._lock fica presa pelo WakeStream durante a gravação inteira (usá-la aqui travava o
        # microfone). O modelo já carregado pode ser compartilhado por outro reconhecedor.
        with _BARGE_LOCK:
            if getattr(self, "_barge", None) is None:
                self._barge = BargeDetector(self)
        return self._barge

    def heard_wake_word(self, wav_path: str) -> bool:
        if not self.available():
            raise RuntimeError(f"reconhecimento local indisponível: {self._error}")
        with self._lock:
            self._wake_rec.Reset()
            result = self._feed(self._wake_rec, wav_path, _Agc())
        all_words = [w["word"] for w in result.get("result", [])]
        heard = self.has_name(all_words)
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
    # Chamar por cima de outra fala (TV, conversa): o nome não está nas 2 primeiras palavras da gravação, mas vem
    # depois de uma pausa — o jeito natural de chamar alguém. name_start marca onde, para a confirmação transcrever
    # só dali em diante (senão a transcrição começaria pela fala da TV e o nome ficaria "no meio").
    PAUSE_BEFORE_NAME = 0.35

    def __init__(self, speech: LocalSpeech) -> None:
        self.speech = speech
        self.heard = False
        self.name_start: float | None = None  # segundos desde o começo da gravação; None = no começo mesmo
        self._texts: list[str] = []
        self._words: list[dict] = []  # palavras finais com tempo (start/end), inclusive [unk]
        self._frames = 0
        speech._lock.acquire()
        self._rec = speech._wake_rec
        self._rec.Reset()
        self._agc = _Agc()
        self._open = True

    def _has_name(self, text: str) -> bool:
        return self.speech.has_name(text.split())

    def _check(self, words: list[dict]) -> bool:
        # Primeiro o nome depois de uma pausa (inclusive depois de fala ininteligível, [unk]): marca o corte.
        for prev, w in zip(words, words[1:]):
            word = w.get("word")
            if (word in self.speech.wake_words and word not in _SHORT_NAMES
                    and w.get("start", 0) - prev.get("end", 0) >= self.PAUSE_BEFORE_NAME):
                self.name_start = float(w["start"])
                return True
        return self.speech.has_name([w.get("word", "") for w in words])

    def feed(self, frame: bytes) -> bool:
        """True só na primeira vez que o nome aparece."""
        if self._open:
            frame = self._agc(frame)
        if not self._open or self.heard:
            if self._open:
                self._rec.AcceptWaveform(frame)
            return False
        self._frames += 1
        # A pausa antes do nome é medida nos resultados FINAIS (tempos confiáveis); o parcial segue só pelo texto.
        # Ligar tempo por palavra no parcial (SetPartialWords) mudava o próprio reconhecimento: medido, -4 a -9 pontos.
        if self._rec.AcceptWaveform(frame):
            res = json.loads(self._rec.Result())
            self._texts.append(res.get("text", ""))
            self._words.extend(res.get("result", []))
            found = self._check(self._words)
        elif self._frames % self.PARTIAL_EVERY == 0:
            partial = json.loads(self._rec.PartialResult()).get("partial", "")
            found = self._has_name(" ".join([*self._texts, partial]))
        else:
            return False
        if found:
            self.heard = True
            return True
        return False

    def close(self) -> tuple[bool, bool, str]:
        """(ouviu o nome, era só o nome, texto ouvido). Libera o reconhecedor."""
        if not self._open:
            return self.heard, False, " ".join(self._texts)
        try:
            res = json.loads(self._rec.FinalResult())
            self._texts.append(res.get("text", ""))
            self._words.extend(res.get("result", []))
        finally:
            self._open = False
            self.speech._lock.release()
        text = " ".join(t for t in self._texts if t).strip()
        if self.heard and self.name_start is None:
            self._check(self._words)  # achado pelo parcial: agora, com os tempos finais, marca onde o nome começa
        heard = self.heard or self._check(self._words)
        words = text.split()
        # "Só o nome" = nenhuma outra palavra. [unk] é o resto da frase que a gramática restrita não conhece
        # ("que horas são"): contar isso como nada jogava o pedido fora sem transcrever.
        only_name = heard and bool(words) and all(w in self.speech.wake_words for w in words)
        self.speech.last_only_name = only_name
        self.speech.last_heard = text
        return heard, only_name, text



class BargeDetector:
    """Procura o nome no áudio que chega ENQUANTO a Cassandra fala (para ela ser interrompida).

    Reconhecedor próprio (não disputa o do WakeStream) com a mesma gramática restrita. Olha só as últimas palavras
    reconhecidas e recomeça a cada resultado final, para a fala dela (que vira [unk]/palavras parecidas) não
    "empurrar" o nome para fora da janela. Usado só pela thread do microfone.
    """

    PARTIAL_EVERY = 3  # checa o parcial a cada ~90 ms

    def __init__(self, speech: LocalSpeech) -> None:
        from vosk import KaldiRecognizer  # noqa: PLC0415

        self.speech = speech
        grammar = speech.wake_words + [w for w in _COMPETITORS if w not in speech.wake_words] + ["[unk]"]
        self._rec = KaldiRecognizer(speech._model, 16000, json.dumps(grammar))
        self._agc = _Agc()
        self._frames = 0

    def reset(self) -> None:
        self._rec.Reset()
        self._agc.reset()
        self._frames = 0

    def _has_name(self, text: str) -> bool:
        words = [w for w in text.split() if w != "[unk]"]
        return any(w in self.speech.wake_words for w in words[-2:])

    def feed(self, frame: bytes) -> bool:
        """True quando o nome aparece (e já recomeça para a próxima vez)."""
        self._frames += 1
        if self._rec.AcceptWaveform(self._agc(frame)):
            text = json.loads(self._rec.Result()).get("text", "")
            self._rec.Reset()
        elif self._frames % self.PARTIAL_EVERY == 0:
            text = json.loads(self._rec.PartialResult()).get("partial", "")
        else:
            return False
        if self._has_name(text):
            self.reset()
            return True
        return False
