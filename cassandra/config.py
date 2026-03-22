import os
from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass
class Settings:
    openai_api_key: str
    openai_model: str = "gpt-4o-mini"
    assistant_name: str = "cassandra"
    assistant_aliases: list[str] | None = None
    input_mode: str = "text"
    transcription_model: str = "gpt-4o-mini-transcribe"
    transcription_language: str = "pt"
    transcription_prompt: str = (
        "A fala principal e em portugues do Brasil. "
        "Preserve nomes proprios e titulos de musicas no idioma original."
    )
    # VAD (Voice Activity Detection) settings
    vad_energy_threshold: int = 400
    vad_silence_duration: float = 0.8
    vad_wake_silence_duration: float = 0.5
    vad_max_duration: float = 30.0
    mic_debug: bool = True
    wake_timeout_seconds: int = 30
    on_sound_path: str = "assets/on.mp3"
    off_sound_path: str = "assets/off.mp3"
    ring_sound_path: str = "assets/ring.mp3"
    startup_sound_path: str = "assets/turn-on.mp3"
    voice_enabled: bool = True
    tts_voice: str = "nova"
    tts_model: str = "tts-1"
    voice_lang: str = "pt-br"
    voice_rate: int = 165
    # Busca na internet via web-agent (skill + ações de rotina que usam o agente)
    web_search_enabled: bool = False


def load_settings() -> Settings:
    load_dotenv()

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    name = os.getenv("ASSISTANT_NAME", "cassandra").strip().lower() or "cassandra"
    raw_aliases = os.getenv(
        "ASSISTANT_ALIASES",
        "cassandra,casandra,cassanda",
    ).strip()
    assistant_aliases = [value.strip().lower() for value in raw_aliases.split(",") if value.strip()]
    input_mode = os.getenv("INPUT_MODE", "text").strip().lower() or "text"
    transcription_model = (
        os.getenv("TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe").strip()
        or "gpt-4o-mini-transcribe"
    )
    transcription_language = os.getenv("TRANSCRIPTION_LANGUAGE", "pt").strip().lower() or "pt"
    transcription_prompt = (
        os.getenv(
            "TRANSCRIPTION_PROMPT",
            "A fala principal e em portugues do Brasil. "
            "Preserve nomes proprios e titulos de musicas no idioma original.",
        ).strip()
        or "A fala principal e em portugues do Brasil. "
        "Preserve nomes proprios e titulos de musicas no idioma original."
    )
    # VAD settings
    vad_energy_threshold = int(os.getenv("VAD_ENERGY_THRESHOLD", "400").strip() or "400")
    vad_silence_duration = float(os.getenv("VAD_SILENCE_DURATION", "0.8").strip() or "0.8")
    vad_wake_silence_duration = float(os.getenv("VAD_WAKE_SILENCE_DURATION", "0.5").strip() or "0.5")
    vad_max_duration = float(os.getenv("VAD_MAX_DURATION", "30.0").strip() or "30.0")

    mic_debug = os.getenv("MIC_DEBUG", "true").strip().lower() in {"1", "true", "yes", "on"}
    wake_timeout_seconds = int(os.getenv("WAKE_TIMEOUT_SECONDS", "30").strip() or "30")
    on_sound_path = os.getenv("ON_SOUND_PATH", "assets/on.mp3").strip() or "assets/on.mp3"
    off_sound_path = os.getenv("OFF_SOUND_PATH", "assets/off.mp3").strip() or "assets/off.mp3"
    ring_sound_path = os.getenv("RING_SOUND_PATH", "assets/ring.mp3").strip() or "assets/ring.mp3"
    startup_sound_path = (
        os.getenv("STARTUP_SOUND_PATH", "assets/turn-on.mp3").strip() or "assets/turn-on.mp3"
    )
    voice_enabled = os.getenv("VOICE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    tts_voice = os.getenv("TTS_VOICE", "nova").strip() or "nova"
    tts_model = os.getenv("TTS_MODEL", "tts-1").strip() or "tts-1"
    voice_lang = os.getenv("VOICE_LANG", "pt-br").strip().lower() or "pt-br"
    voice_rate = int(os.getenv("VOICE_RATE", "165").strip() or "165")
    web_search_enabled = os.getenv("WEB_SEARCH_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY nao configurada. Defina a variavel de ambiente antes de iniciar."
        )
    if input_mode not in {"text", "mic"}:
        raise RuntimeError("INPUT_MODE invalido. Use 'text' ou 'mic'.")
    if len(transcription_language) != 2:
        raise RuntimeError("TRANSCRIPTION_LANGUAGE invalido. Use codigo ISO-639-1, ex: 'pt'.")
    if not assistant_aliases:
        assistant_aliases = [name]
    if vad_energy_threshold < 50:
        raise RuntimeError("VAD_ENERGY_THRESHOLD deve ser >= 50.")
    if vad_wake_silence_duration < 0.2:
        raise RuntimeError("VAD_WAKE_SILENCE_DURATION deve ser >= 0.2 segundos.")
    if vad_silence_duration < 0.3:
        raise RuntimeError("VAD_SILENCE_DURATION deve ser >= 0.3 segundos.")
    if vad_max_duration < 2.0:
        raise RuntimeError("VAD_MAX_DURATION deve ser >= 2.0 segundos.")
    if wake_timeout_seconds < 1:
        raise RuntimeError("WAKE_TIMEOUT_SECONDS deve ser >= 1.")
    if voice_rate < 80 or voice_rate > 320:
        raise RuntimeError("VOICE_RATE deve estar entre 80 e 320.")

    return Settings(
        openai_api_key=api_key,
        openai_model=model,
        assistant_name=name,
        assistant_aliases=assistant_aliases,
        input_mode=input_mode,
        transcription_model=transcription_model,
        transcription_language=transcription_language,
        transcription_prompt=transcription_prompt,
        vad_energy_threshold=vad_energy_threshold,
        vad_silence_duration=vad_silence_duration,
        vad_wake_silence_duration=vad_wake_silence_duration,
        vad_max_duration=vad_max_duration,
        mic_debug=mic_debug,
        wake_timeout_seconds=wake_timeout_seconds,
        on_sound_path=on_sound_path,
        off_sound_path=off_sound_path,
        ring_sound_path=ring_sound_path,
        startup_sound_path=startup_sound_path,
        voice_enabled=voice_enabled,
        tts_voice=tts_voice,
        tts_model=tts_model,
        voice_lang=voice_lang,
        voice_rate=voice_rate,
        web_search_enabled=web_search_enabled,
    )
