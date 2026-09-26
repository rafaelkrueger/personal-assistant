from __future__ import annotations

from collections.abc import Iterator

from cassandra import llm_settings


class LLMService:
    """Fachada única para o LLM. A cada chamada pergunta ao llm_settings qual provider está ativo
    (OpenAI ou DeepSeek), então trocar o modelo pela UI vale na hora, sem reiniciar.

    Texto (answer, answer_stream, is_dismissal, create_completion) usa o provider ativo.
    Voz (synthesize_speech) e transcrição (transcribe_audio_file) usam sempre a OpenAI — a DeepSeek não tem
    áudio. Sem chave da OpenAI essas duas levantam RuntimeError e a voz cai no TTS local (ver voice.py).
    """

    @property
    def client(self):
        return llm_settings.chat_client()[0]

    @property
    def model(self) -> str:
        return llm_settings.chat_client()[1]

    def create_completion(self, messages: list[dict], *, fast: bool = False, **kwargs):
        """chat.completions.create no provider ativo. fast=True usa o modelo rápido/barato do provider
        (gpt-4o-mini na OpenAI) — para classificações curtas das skills."""
        client, model, fast_model, extra = llm_settings.chat_client()
        if extra:
            kwargs["extra_body"] = {**extra, **kwargs.get("extra_body", {})}
        return client.chat.completions.create(
            model=fast_model if fast else model,
            messages=messages,
            **kwargs,
        )

    @staticmethod
    def _messages(
        user_text: str,
        system_prompt: str | None,
        history: list[dict[str, str]] | None,
    ) -> list[dict]:
        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_text})
        return messages

    def answer(
        self,
        user_text: str,
        system_prompt: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        response = self.create_completion(
            self._messages(user_text, system_prompt, history),
            temperature=0.5,
        )
        return response.choices[0].message.content or "Nao consegui responder agora."

    def answer_stream(
        self,
        user_text: str,
        system_prompt: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> Iterator[str]:
        stream = self.create_completion(
            self._messages(user_text, system_prompt, history),
            temperature=0.5,
            stream=True,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    def is_dismissal(self, text: str) -> bool:
        """Returns True if the user's utterance signals they want to end the session.

        Uses the provider's fast model with temperature=0 and max_tokens=3 for speed and
        minimal cost. The model responds with 'yes' or 'no' only.
        """
        response = self.create_completion(
            fast=True,
            temperature=0,
            max_tokens=3,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You classify user intent for a voice assistant named Cassandra. "
                        "Reply with exactly 'yes' if the user wants to end, dismiss, or say goodbye to the assistant. "
                        "Reply with exactly 'no' if the user wants to continue the conversation or issue a command. "
                        "The user speaks Brazilian Portuguese. "
                        "Dismissal examples: 'tchau', 'dispensada', 'pode ir', 'obrigado', 'valeu', 'até logo', "
                        "'pode descansar', 'pode desligar', 'foi isso', 'ok obrigado', 'só isso', 'era só isso'. "
                        "Command examples: 'qual o tempo?', 'me conta uma piada', 'e amanhã?', 'como funciona?', "
                        "'valeu a dica, agora me fala...', 'obrigado pela resposta mas...'."
                    ),
                },
                {"role": "user", "content": text},
            ],
        )
        answer = (response.choices[0].message.content or "").strip().lower()
        return answer.startswith("yes") or answer == "sim"

    def synthesize_speech(
        self,
        text: str,
        model: str = "tts-1",
        voice: str = "nova",
    ) -> bytes:
        # sem novas tentativas: se falhar (ex.: sem créditos), a voz grátis assume na hora
        response = llm_settings.audio_client().with_options(max_retries=0).audio.speech.create(
            model=model,
            voice=voice,
            input=text,
        )
        return response.content

    def transcribe_audio_file(
        self,
        audio_path: str,
        model: str,
        language: str = "pt",
        prompt: str | None = None,
    ) -> str:
        with open(audio_path, "rb") as audio_file:
            response = llm_settings.audio_client().audio.transcriptions.create(
                model=model,
                file=audio_file,
                language=language,
                prompt=prompt,
            )
        return (response.text or "").strip()
