from __future__ import annotations

from collections.abc import Iterator

from openai import OpenAI


class LLMService:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def answer(
        self,
        user_text: str,
        system_prompt: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_text})

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.5,
        )
        return response.choices[0].message.content or "Nao consegui responder agora."

    def answer_stream(
        self,
        user_text: str,
        system_prompt: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> Iterator[str]:
        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_text})

        stream = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.5,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    def is_dismissal(self, text: str) -> bool:
        """Returns True if the user's utterance signals they want to end the session.

        Uses gpt-4o-mini with temperature=0 and max_tokens=3 for speed and
        minimal cost. The model responds with 'yes' or 'no' only.
        """
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
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
        response = self.client.audio.speech.create(
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
            response = self.client.audio.transcriptions.create(
                model=model,
                file=audio_file,
                language=language,
                prompt=prompt,
            )
        return (response.text or "").strip()
