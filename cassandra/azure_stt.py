"""Transcrição pelo Azure (Microsoft Speech), a mesma conta/chave da voz (Configurações > Modelo de IA).

API REST de áudio curto: manda o WAV de 16 kHz que o gravador já produz e recebe o texto. O plano gratuito F0 dá
5 horas de transcrição por mês; esgotado, o Azure recusa (sem cobrar) e a Cassandra usa a OpenAI ou a local.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from cassandra.voice import _azure_config

# O idioma da transcrição vem como código curto (TRANSCRIPTION_LANGUAGE=pt); o Azure quer a variante regional.
_LOCALES = {"pt": "pt-BR", "en": "en-US", "es": "es-ES"}


def transcribe(wav_path: str, language: str = "pt") -> str:
    key, region, _voice = _azure_config()
    if not key:
        raise RuntimeError("chave do Azure não configurada")
    locale = _LOCALES.get(language, language or "pt-BR")
    with open(wav_path, "rb") as fh:
        audio = fh.read()
    req = urllib.request.Request(
        f"https://{region}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1"
        f"?language={locale}&format=simple",
        data=audio, method="POST",
        headers={"Ocp-Apim-Subscription-Key": key, "User-Agent": "cassandra",
                 "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read()[:160]!r}") from exc
    from cassandra import usage_log  # noqa: PLC0415

    usage_log.record_stt("azure", "azure", usage_log.wav_seconds(wav_path))  # cobrado mesmo sem fala
    status = data.get("RecognitionStatus")
    if status == "Success":
        return (data.get("DisplayText") or "").strip()
    if status in ("NoMatch", "InitialSilenceTimeout", "BabbleTimeout"):
        return ""  # não havia fala reconhecível
    raise RuntimeError(f"Azure: {status or data}")
