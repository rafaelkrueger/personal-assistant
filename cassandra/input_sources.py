from __future__ import annotations

import glob
import os
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher

from cassandra import llm_settings
from cassandra import speech_state
from cassandra.mic_monitor import monitor
from cassandra.openai_client import LLMService

# Frases que modelos de transcrição "alucinam" com silêncio/ruído (vêm de legendas de vídeos).
_HALLUCINATIONS = ("legendas pela comunidade", "amaraorg", "obrigado por assistir", "obrigada por assistir",
                   "inscrevase no canal", "se inscreva no canal", "legenda adriana", "transcricao e legendas",
                   "subtitles by", "thanks for watching", "thank you for watching")
_OPENAI_RETRY_AFTER = 600  # depois de uma falha da OpenAI (ex.: sem créditos), usa só o local por 10 min
_BARGE_WHILE_SPEAKING = os.getenv("BARGE_IN_WHILE_SPEAKING", "").strip().lower() in {"1", "true", "sim"}
_SESSION_MIN_VOICED = 2  # quadros com voz exigidos numa sessão ativa (esperando o nome são 7)


@dataclass
class InputEvent:
    text: str
    exit_requested: bool = False
    wake_signaled: bool = False  # o som de ativação já tocou (nome detectado ao vivo)


class TextInputSource:
    def read(self, wake_phase: bool = False, max_wait: float | None = None,
             silence: float | None = None) -> InputEvent:
        _ = wake_phase, silence
        raw_text = input("\nVoce: ").strip()
        if raw_text.lower() in {"sair", "exit", "quit"}:
            return InputEvent(text="", exit_requested=True)
        return InputEvent(text=raw_text)


class MicrophoneInputSource:
    """Captures one complete spoken utterance per read() call using VAD.

    Unlike the previous chunked approach, this class streams audio continuously
    via pyaudio and uses energy-based VAD to detect when the user starts and
    finishes speaking. The full utterance is sent to the transcription API in
    one shot, eliminating chunk-boundary artifacts and mid-sentence cut-offs.

    With wake_word_engine="local" (default), while waiting for the name each
    utterance is first checked on the device by Vosk (cassandra/local_speech.py):
    without the name it is discarded there and nothing goes to the API. Only
    utterances with the name (and everything said during an active session)
    are transcribed — by OpenAI or locally, per transcription_provider.
    """

    def __init__(
        self,
        llm: LLMService,
        transcription_model: str,
        transcription_language: str,
        transcription_prompt: str,
        vad_energy_threshold: int = 400,
        vad_silence_duration: float = 0.8,
        vad_wake_silence_duration: float = 0.5,
        vad_max_duration: float = 30.0,
        interrupt_event: threading.Event | None = None,
        debug: bool = True,
        assistant_name: str = "cassandra",
        wake_words: list[str] | None = None,
        wake_word_engine: str = "local",
        transcription_provider: str = "auto",
        vosk_model_path: str = "models/vosk-model-small-pt-0.3",
        wait_for_device: bool = False,
        on_wake=None,
    ) -> None:
        self.llm = llm
        self.transcription_model = transcription_model
        self.transcription_language = transcription_language
        self._azure_down_until = 0.0  # depois de uma falha do Azure, usa a OpenAI/local por um tempo
        self.transcription_prompt = transcription_prompt
        self.vad_wake_silence_duration = vad_wake_silence_duration
        self.interrupt_event = interrupt_event
        self.debug = debug
        self._last_capture_error_at = 0.0
        self.assistant_name = assistant_name
        self.wait_for_device = wait_for_device
        self._mic_present: bool | None = None
        self.transcription_provider = transcription_provider
        self._openai_down_until = 0.0

        self.local = None
        if wake_word_engine == "local" or transcription_provider in {"auto", "local"}:
            from cassandra.local_speech import LocalSpeech  # noqa: PLC0415

            self.local = LocalSpeech(wake_words or [assistant_name], model_path=vosk_model_path, debug=debug)
            self.local.preload()
        self.local_wake = wake_word_engine == "local"
        self.on_wake = on_wake  # toca o som de ativação quando o nome é reconhecido
        self.on_barge = None  # chamado quando a pessoa diz o nome enquanto a Cassandra fala (interromper)
        self._signaled = False  # nome confirmado (o bip já tocou)
        self._candidate = False  # o Vosk achou o nome ao vivo, falta a transcrição confirmar
        self.wake_words = [w.strip().lower() for w in (wake_words or [assistant_name]) if w.strip()]

        from cassandra.vad_recorder import VadRecorder  # noqa: PLC0415

        self._recorder = VadRecorder(
            energy_threshold=vad_energy_threshold,
            silence_duration=vad_silence_duration,
            max_duration=vad_max_duration,
        )

    def read(self, wake_phase: bool = False, max_wait: float | None = None,
             silence: float | None = None) -> InputEvent:
        """Block until a complete utterance is spoken, then transcribe it.

        Args:
            wake_phase: When True, uses the shorter wake-word silence threshold
                so activation is faster after the user says just the assistant name.
            silence: pausa que encerra a fala (fora da espera do nome); o modo conversa aceita pausas maiores.
        """
        if self.wait_for_device and not self._check_microphone():
            time.sleep(3)
            return InputEvent(text="")
        silence_override = self.vad_wake_silence_duration if wake_phase else silence
        self._signaled = False
        self._candidate = False
        try:
            text = self._capture_and_transcribe(silence_override, wake_phase=wake_phase, max_wait=max_wait)
        except Exception as exc:  # noqa: BLE001
            now = time.monotonic()
            if now - self._last_capture_error_at > 5.0:
                self._last_capture_error_at = now
                print(f"[MIC] Entrada de audio indisponivel: {exc}")
                monitor.event("error", f"Não consegui usar o microfone: {exc}")
            self._recorder.close()  # reabre na próxima: o PortAudio só enxerga aparelhos novos ao reiniciar
            time.sleep(1.0)
            return InputEvent(text="")
        if text.lower() in {"sair", "exit", "quit"}:
            return InputEvent(text="", exit_requested=True)
        return InputEvent(text=text, wake_signaled=self._signaled)

    def _mark_candidate(self) -> None:
        """O Vosk achou o nome ao vivo: só um CANDIDATO. Encerra a gravação na próxima pausa (para verificar logo),
        mas não toca o bip nem ativa nada — quem confirma é a transcrição (ver _verify_name)."""
        if not self._candidate:
            self._candidate = True
            monitor.event("wake", "Nome talvez ouvido — conferindo")

    def _signal_wake(self) -> None:
        """Nome confirmado: toca o som de ativação (e pausa a música, via on_wake)."""
        if self._signaled:
            return
        self._signaled = True
        monitor.event("wake", "Nome confirmado")
        if self.on_wake:
            try:
                self.on_wake()
            except Exception:  # noqa: BLE001 — o som nunca pode derrubar a escuta
                pass

    def _capture_and_transcribe(self, silence_duration: float | None = None, wake_phase: bool = False,
                                max_wait: float | None = None) -> str:
        # Esperando o nome: reconhece ao vivo enquanto grava (o som de ativação sai na hora).
        stream = self.local.stream() if (wake_phase and self.local_wake and self._local_ready()) else None

        # Nome dito POR CIMA da fala dela: desligado por padrão — com a voz dela saindo da caixa, o detector local
        # confundia trechos da fala com o nome (18 falsos positivos em 15 falas testadas) e ela se interrompia
        # sozinha. Interromper enquanto ela PROCESSA um pedido (pesquisa, agentes) continua valendo.
        barge = (self.local.barge_detector()
                 if _BARGE_WHILE_SPEAKING and self.local is not None and self._local_ready() else None)
        if barge is not None:
            barge.reset()

        def on_busy_frame(frame: bytes) -> bool:
            """Enquanto ela fala: o nome dito por cima interrompe tudo e a gravação vira o pedido novo."""
            if barge is None or not barge.feed(frame):
                return False
            if speech_state.said_recently(self.local.wake_words):
                return False  # foi ela mesma dizendo o próprio nome ("eu sou a Cassandra")
            speech_state.cancel()
            monitor.event("wake", "Interrompida: nome ouvido enquanto ela falava")
            if self.on_barge:
                try:
                    self.on_barge()
                except Exception:  # noqa: BLE001
                    pass
            self._signal_wake()
            return True

        def on_frame(frame: bytes) -> bool:
            """True = o nome talvez foi dito (o gravador pode encerrar na primeira pausa depois dele)."""
            if stream is not None and stream.feed(frame):
                self._mark_candidate()
            return self._candidate

        try:
            wav_path = self._recorder.record_utterance(
                silence_duration=silence_duration,
                interrupt_event=self.interrupt_event,
                on_frame=on_frame if stream is not None else None,
                max_wait=max_wait,
                # Na sessão (depois do bip) a pessoa está falando com ela: basta um pouco de voz (o chiado dá 0).
                min_voiced=None if wake_phase else _SESSION_MIN_VOICED,
                on_busy_frame=on_busy_frame if barge is not None else None,
            )
        finally:
            result = stream.close() if stream is not None else None
        if not wav_path:
            return ""

        try:
            if getattr(self._recorder, "last_barged", False):
                # O nome foi dito por cima da fala dela (o WakeStream não ouviu esse trecho): é um pedido com o nome.
                text = self._with_wake_word(self._transcribe(wav_path))
            elif wake_phase and self.local_wake and self._local_ready():
                # Sem o nome, nada vai para a API.
                heard, only_name, heard_text = result if result else (self.local.heard_wake_word(wav_path),
                                                                       self.local.last_only_name,
                                                                       getattr(self.local, "last_heard", ""))
                if not heard:
                    if heard_text:  # sem nada reconhecível é só ruído: não registra
                        monitor.event("no_wake", f"Sem o nome — ouvido: “{heard_text}”")
                    return ""
                # O Vosk (gramática restrita) força falas parecidas para o nome e disparava com conversa da casa e
                # TV ("...porque são 2 senadores..." virava "cassandra, ..."). A transcrição de verdade confirma:
                # o nome tem que estar lá, no começo ou no fim da frase. Só então ela bipa e ativa.
                confirmed, full = self._verify_name(wav_path, heard_text)
                if not confirmed:
                    monitor.event("no_wake", f"Falso alarme descartado — a transcrição não tem o nome: “{full}”")
                    return ""
                self._signal_wake()
                rest = self._without_name(full)
                # Mesmo que o Vosk achasse que foi "só o nome", vale o que a transcrição ouviu depois dele.
                text = f"{self.assistant_name}, {rest}" if rest else self.assistant_name
            else:
                text = self._transcribe(wav_path)
        finally:
            os.unlink(wav_path)

        text = (text or "").strip()
        if text and (speech_state.busy() or speech_state.is_echo(text)):
            # Era a voz dela mesma (captada no fim de uma fala, ou repetindo algo que ela acabou de dizer): responder
            # a isso fazia a Cassandra entrar em loop, conversando consigo mesma.
            monitor.event("transcribed", f"Descartado (era a própria voz da Cassandra): “{text}”")
            return ""
        if text and self._hallucinated(text):
            monitor.event("transcribed", f"Descartado (a transcrição inventou texto com áudio ruim): “{text}”")
            text = ""
        else:
            monitor.event("transcribed", f"Transcrito: “{text}”" if text else "Transcrição vazia (silêncio ou ruído)")

        if self.debug:
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[MIC {ts}] {text or '<silencio>'}")

        return text

    def _check_microphone(self) -> bool:
        """Há algum aparelho de captura (ex.: microfone USB)? Loga só quando muda."""
        present = bool(glob.glob("/proc/asound/card*/pcm*c"))
        if present != self._mic_present:
            monitor.set(present=present)
            if present:
                print("[MIC] Microfone detectado — ouvindo (diga o nome para chamar).", flush=True)
                monitor.event("status", "Microfone conectado")
                self._recorder.close()  # o PortAudio precisa reiniciar para ver o aparelho novo
            else:
                print("[MIC] Nenhum microfone conectado — aguardando você plugar um. "
                      "O chat da UI continua funcionando.", flush=True)
                monitor.set(phase="sem microfone", device="", rate=0)
                monitor.event("status", "Nenhum microfone conectado — aguardando você plugar um")
            self._mic_present = present
        return present

    def _local_ready(self) -> bool:
        return self.local is not None and self.local.available()

    def _transcribe(self, wav_path: str) -> str:
        # Provedor e modelo vêm das Configurações > Modelo de IA > Transcrição (valem na hora); o .env é o padrão.
        settings = llm_settings.get()
        provider = settings.get("stt_provider") or self.transcription_provider
        model = settings.get("stt_model") or self.transcription_model
        if provider == "azure":
            if time.monotonic() >= self._azure_down_until:
                try:
                    from cassandra import azure_stt  # noqa: PLC0415

                    return azure_stt.transcribe(wav_path, self.transcription_language)
                except Exception as exc:  # noqa: BLE001 — franquia do mês esgotada, rede...: OpenAI ou local
                    self._azure_down_until = time.monotonic() + _OPENAI_RETRY_AFTER
                    print(f"[MIC] Transcrição do Azure falhou ({str(exc)[:160]}); usando a OpenAI/local por 10 min.",
                          flush=True)
            provider = "auto"
        if provider == "local" and self._local_ready():
            return self.local.transcribe(wav_path)
        use_openai = provider == "openai" or (
            provider in ("auto", "local")
            and bool(settings["openai_api_key"])
            and time.monotonic() >= self._openai_down_until
        )
        if use_openai:
            try:
                return self.llm.transcribe_audio_file(
                    wav_path,
                    model=model,
                    language=self.transcription_language,
                    prompt=self.transcription_prompt,
                )
            except Exception as exc:  # noqa: BLE001
                if provider == "openai" or not self._local_ready():
                    raise
                self._openai_down_until = time.monotonic() + _OPENAI_RETRY_AFTER
                print(f"[MIC] Transcrição da OpenAI falhou ({exc}); usando a local por 10 min.")
        if not self._local_ready():
            raise RuntimeError("Sem transcrição disponível: nem chave da OpenAI nem modelo local (Vosk).")
        return self.local.transcribe(wav_path)

    def _hallucinated(self, text: str) -> bool:
        """Com áudio ruim o modelo de transcrição inventa: repete o texto de instrução (TRANSCRIPTION_PROMPT)
        ou solta frases de legenda. Isso nunca é um pedido de verdade."""
        norm = lambda t: re.sub(r"[^a-z0-9 ]+", "", unicodedata.normalize("NFKD", t.lower())  # noqa: E731
                                .encode("ascii", "ignore").decode()).strip()
        t = norm(text)
        if not t:
            return False
        prompt = norm(self.transcription_prompt or "")
        # só quando repete a maior parte do texto de instrução (um pedido curto que aparece nele é legítimo)
        if prompt and len(t) >= 0.6 * len(prompt) and (t in prompt or prompt in t
                                                      or SequenceMatcher(None, t, prompt).ratio() >= 0.6):
            return True
        return any(p in t for p in _HALLUCINATIONS)

    # ── Confirmação do nome ─────────────────────────────────────────────────

    _VOCATIVES = {"o", "oi", "ei", "e", "ola", "hey", "alo"}
    _NAME_RATIO = 0.72  # "casandra", "kassandra", "sandra", "alessandra" passam; "casa", "sandro", "cassino" não

    @staticmethod
    def _tokens(text: str) -> list[str]:
        t = unicodedata.normalize("NFKD", (text or "").lower())
        t = "".join(c for c in t if not unicodedata.combining(c))
        return re.findall(r"[a-z]+", t)

    def _is_name(self, word: str) -> bool:
        return word in self.wake_words or SequenceMatcher(None, word, self.assistant_name.lower()).ratio() >= \
            self._NAME_RATIO

    def _name_in(self, text: str) -> bool:
        """O nome aparece como chamado: nas 3 primeiras palavras ("Cassandra, ...", "ô Cassandra, ...") ou nas 2
        últimas ("..., Cassandra?"). No meio da frase é alguém falando DELA, não com ela."""
        words = self._tokens(text)
        full = self.assistant_name.lower()
        whole = [w for w in words[:3] + words[-2:] if SequenceMatcher(None, w, full).ratio() >= 0.85]
        # Variações ("Sandra", "Alessandra") só como a 1ª palavra, depois de um "ô/oi/ei" no máximo: "casa da
        # Sandra" não chama. O nome inteiro vale nas 3 primeiras ou nas 2 últimas palavras.
        first = next((w for w in words if w not in self._VOCATIVES), "")
        return bool(whole) or (bool(first) and self._is_name(first))

    def _without_name(self, text: str) -> str:
        """O pedido sem o nome (e sem vocativos em volta), para virar "Cassandra, <pedido>"."""
        parts = (text or "").strip().split()
        while parts and (self._is_name(("".join(self._tokens(parts[0])) or "x")) or
                         "".join(self._tokens(parts[0])) in self._VOCATIVES):
            parts.pop(0)
        while parts and self._is_name("".join(self._tokens(parts[-1])) or "x"):
            parts.pop()
        return " ".join(parts).strip(" ,.;:!?")

    def _verify_name(self, wav_path: str, vosk_text: str) -> tuple[bool, str]:
        """(confirmado, transcrição). Sem transcrição disponível (sem internet, cota do Azure...), aceita só se o
        Vosk ouviu o nome completo "cassandra" como a 1ª palavra — melhor que ficar surda."""
        try:
            full = (self._transcribe(wav_path) or "").strip()
        except Exception as exc:  # noqa: BLE001
            print(f"[WAKE] Sem transcrição para conferir o nome ({str(exc)[:120]}).", flush=True)
            words = [w for w in (vosk_text or "").split() if w != "[unk]"]
            return bool(words) and words[0] == self.assistant_name.lower(), vosk_text
        return self._name_in(full), full

    def _with_wake_word(self, text: str) -> str:
        """O nome foi detectado localmente, mas a transcrição completa às vezes o erra ("sandra que horas
        são"). Garante que o texto comece pelo nome, para o assistente reconhecer a ativação."""
        words = (text or "").strip().split(" ", 1)
        first = words[0].strip(" ,.:;!?").lower() if words and words[0] else ""
        rest = words[1].strip() if len(words) > 1 else ""
        if first and SequenceMatcher(None, first, self.assistant_name.lower()).ratio() >= 0.6:
            return f"{self.assistant_name}, {rest}".strip(" ,")
        return f"{self.assistant_name}, {text}".strip(" ,")

    def close(self) -> None:
        self._recorder.close()
