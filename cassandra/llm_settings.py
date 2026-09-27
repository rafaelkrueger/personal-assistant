"""Configuração runtime do LLM: provider ativo (openai | deepseek | local) + modelo + chave de cada um.

Editável pela UI (Configurações > Modelo de IA, rota /api/llm) sem reiniciar — cada chamada do LLMService
pergunta aqui qual provider usar. Começa com os valores do .env (LLM_PROVIDER, OPENAI_API_KEY, OPENAI_MODEL,
DEEPSEEK_API_KEY, DEEPSEEK_MODEL) e o que for salvo pela UI vai para data/llm_settings.json, que passa a ter
prioridade sobre o .env. Esse arquivo guarda chaves: fica fora do git (.gitignore).

Mesmo desenho do settings_store.py do maestro e do llm_settings.py do editor.

Local = os modelos do Llama Desk (Ollama) no PC, pelas rotas /v1 compatíveis com a OpenAI que ele expõe na
rede. Se o PC estiver desligado ou o Llama Desk falhar, o LLMService usa a OpenAI no lugar (ver
openai_client.py).

A DeepSeek só faz texto (chat). Voz (TTS) e transcrição do microfone (STT) continuam sempre na OpenAI:
sem chave da OpenAI, a voz cai no TTS local (espeak) e o modo microfone não transcreve.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_STORE_FILE = Path("data/llm_settings.json")
_lock = threading.Lock()

PROVIDERS = ("openai", "deepseek", "local")
# Transcrição do microfone (o que a pessoa fala vira texto). auto = OpenAI e, se falhar, a local (Vosk).
STT_PROVIDERS = ("auto", "openai", "azure", "local")

# Nomes aposentados pela DeepSeek (deepseek-chat/reasoner saíram em 2026-07-24; hoje "deepseek-chat" é só um
# apelido do deepseek-flash). Mesmo mapeamento do editor.
_DEEPSEEK_MODEL_ALIASES = {
    "deepseek-chat": "deepseek-flash",
    "deepseek-reasoner": "deepseek-flash",
    "deepseek-v4-flash": "deepseek-flash",
    "deepseek-v4-flash-vision-exp": "deepseek-flash",
}

# Modelo barato/rápido para classificações curtas (dispensa, intenção de busca, rotinas, agenda).
_OPENAI_FAST_MODEL = "gpt-4o-mini"


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


_DEFAULTS: dict[str, Any] = {
    "llm_provider": _env("LLM_PROVIDER", "openai").lower() or "openai",
    "openai_api_key": _env("OPENAI_API_KEY"),
    "openai_model": _env("OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini",
    "deepseek_api_key": _env("DEEPSEEK_API_KEY"),
    "deepseek_model": _env("DEEPSEEK_MODEL", "deepseek-flash") or "deepseek-flash",
    "deepseek_base_url": _env("DEEPSEEK_BASE_URL", "https://api.deepseek.com") or "https://api.deepseek.com",
    # Modelos locais do Llama Desk no PC (mesmos nomes de campo do maestro). O modelo vem da lista do Llama Desk.
    "local_llm_base_url": _env("LOCAL_LLM_BASE_URL", "http://desktop-cc6nlck.local:8002")
    or "http://desktop-cc6nlck.local:8002",
    "local_llm_model": _env("LOCAL_LLM_MODEL"),
    # Transcrição do microfone (Configurações > Modelo de IA > Transcrição). O .env é o padrão.
    "stt_provider": _env("TRANSCRIPTION_PROVIDER", "auto").lower() or "auto",
    "stt_model": _env("TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe") or "gpt-4o-mini-transcribe",
    # Voz da Cassandra pelo Azure (Microsoft Speech). Sem chave, a voz é a da OpenAI (ver voice.py).
    "azure_speech_key": _env("AZURE_SPEECH_KEY"),
    "azure_speech_region": _env("AZURE_SPEECH_REGION", "brazilsouth") or "brazilsouth",
    "azure_tts_voice": _env("AZURE_TTS_VOICE", "pt-BR-FranciscaNeural") or "pt-BR-FranciscaNeural",
}
if _DEFAULTS["llm_provider"] not in PROVIDERS:
    _DEFAULTS["llm_provider"] = "openai"

_state: dict[str, Any] = dict(_DEFAULTS)
_clients: dict[tuple[str, str], OpenAI] = {}


def resolve_deepseek_model(name: str) -> str:
    return _DEEPSEEK_MODEL_ALIASES.get(name, name)


def _load() -> None:
    if not _STORE_FILE.exists():
        return
    try:
        saved = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return
    if not isinstance(saved, dict):
        return
    # Chave vazia salva não apaga a do .env (mesma regra do update()).
    _state.update({k: v for k, v in saved.items() if k in _DEFAULTS and v not in (None, "")})
    if _state["llm_provider"] not in PROVIDERS:
        _state["llm_provider"] = "openai"
    _state["deepseek_model"] = resolve_deepseek_model(_state["deepseek_model"])


def _save() -> None:
    _STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STORE_FILE.write_text(json.dumps(_state, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(_STORE_FILE, 0o600)
    except OSError:
        pass


_load()


def get() -> dict[str, Any]:
    with _lock:
        return dict(_state)


def _preview(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 8:
        return "•" * len(secret)
    return f"{secret[:3]}···{secret[-4:]}"


def get_public() -> dict[str, Any]:
    """Versão segura para a UI: nunca a chave em si, só se está configurada e um preview curto."""
    s = get()
    return {
        "llm_provider": s["llm_provider"],
        "providers": list(PROVIDERS),
        "openai_model": s["openai_model"],
        "openai_api_key_set": bool(s["openai_api_key"]),
        "openai_api_key_preview": _preview(s["openai_api_key"]),
        "deepseek_model": s["deepseek_model"],
        "deepseek_base_url": s["deepseek_base_url"],
        "deepseek_api_key_set": bool(s["deepseek_api_key"]),
        "deepseek_api_key_preview": _preview(s["deepseek_api_key"]),
        # Microfone depende da OpenAI; a voz usa o Azure se houver chave, senão a OpenAI.
        "audio_available": bool(s["openai_api_key"]),
        "local_llm_base_url": s["local_llm_base_url"],
        "local_llm_model": s["local_llm_model"],
        "stt_provider": s["stt_provider"],
        "stt_providers": list(STT_PROVIDERS),
        "stt_model": s["stt_model"],
        "azure_speech_key_set": bool(s["azure_speech_key"]),
        "azure_speech_key_preview": _preview(s["azure_speech_key"]),
        "azure_speech_region": s["azure_speech_region"],
        "azure_tts_voice": s["azure_tts_voice"],
    }


def update(fields: dict[str, Any]) -> dict[str, Any]:
    provider = fields.get("llm_provider")
    if provider is not None and provider not in PROVIDERS:
        raise ValueError(f"llm_provider inválido: {provider!r} (use openai, deepseek ou local)")
    stt = fields.get("stt_provider")
    if stt is not None and stt not in STT_PROVIDERS:
        raise ValueError(f"stt_provider inválido: {stt!r} (use {', '.join(STT_PROVIDERS)})")
    with _lock:
        for key, value in fields.items():
            if key not in _DEFAULTS:
                continue
            if value is None or (isinstance(value, str) and not value.strip()):
                continue  # campo vazio no formulário = "não mexe"; nunca apaga uma chave já salva
            _state[key] = value.strip() if isinstance(value, str) else value
        _state["deepseek_model"] = resolve_deepseek_model(_state["deepseek_model"])
        _save()
    return get_public()


def active_provider() -> str:
    return get()["llm_provider"]


def _client(api_key: str, base_url: str = "", **options: Any) -> OpenAI:
    key = (api_key, base_url)
    with _lock:
        client = _clients.get(key)
        if client is None:
            kwargs: dict[str, Any] = {"api_key": api_key, **options}
            if base_url:
                kwargs["base_url"] = base_url
            client = _clients[key] = OpenAI(**kwargs)
        return client


# Depois de uma falha do modelo local (PC desligado, Llama Desk fora, IA pausada), usa a OpenAI por um tempo em
# vez de esperar a falha de novo em cada pedido.
_LOCAL_RETRY_AFTER = 120
_local_down_until = 0.0


def mark_local_failed(reason: str) -> bool:
    """Registra a falha do local. True se a OpenAI pode assumir (há chave)."""
    global _local_down_until
    import time  # noqa: PLC0415

    first = time.monotonic() >= _local_down_until
    _local_down_until = time.monotonic() + _LOCAL_RETRY_AFTER
    can = bool(get()["openai_api_key"])
    if first:
        print(f"[LLM] Modelo local falhou ({reason[:160]}); "
              f"{'usando a OpenAI' if can else 'sem OpenAI para assumir'} por {_LOCAL_RETRY_AFTER // 60} min.",
              flush=True)
    return can


def _openai_client() -> tuple[OpenAI, str, str, dict[str, Any]]:
    s = get()
    if not s["openai_api_key"]:
        raise RuntimeError("Chave da OpenAI não configurada (Configurações > Modelo de IA).")
    return _client(s["openai_api_key"]), s["openai_model"], _OPENAI_FAST_MODEL, {}


def local_models() -> list[str]:
    """Modelos instalados no Llama Desk (Ollama no PC), para o seletor da UI."""
    import urllib.request  # noqa: PLC0415

    base = get()["local_llm_base_url"].rstrip("/")
    with urllib.request.urlopen(base + "/v1/models", timeout=8) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return sorted(m["id"] for m in data.get("data", []) if m.get("id"))


def chat_client() -> tuple[OpenAI, str, str, dict[str, Any]]:
    """(cliente, modelo principal, modelo rápido, extra_body) do provider ativo agora."""
    s = get()
    if s["llm_provider"] == "local":
        import time  # noqa: PLC0415

        if time.monotonic() < _local_down_until and s["openai_api_key"]:
            return _openai_client()  # o local falhou há pouco: a OpenAI segura até ele voltar
        if not s["local_llm_model"]:
            raise RuntimeError("Modelo local não escolhido (Configurações > Modelo de IA).")
        # CPU: a 1ª resposta de um modelo frio pode passar de um minuto. Sem novas tentativas: se o PC estiver
        # desligado, a falha sai logo e a OpenAI assume.
        client = _client("local", s["local_llm_base_url"].rstrip("/") + "/v1", timeout=240.0, max_retries=0)
        # Modelos que "pensam" (qwen3...) levavam ~80 s por resposta; sem o raciocínio, ~1-4 s.
        extra = {"reasoning_effort": "none"}
        return client, s["local_llm_model"], s["local_llm_model"], extra
    if s["llm_provider"] == "deepseek":
        if not s["deepseek_api_key"]:
            raise RuntimeError("Chave da DeepSeek não configurada (Configurações > Modelo de IA).")
        model = resolve_deepseek_model(s["deepseek_model"])
        # O deepseek-flash vem com raciocínio ligado: mais lento e gasta os tokens antes de responder (com
        # max_tokens pequeno a resposta sai vazia). Para uma assistente de voz, resposta direta é o certo.
        extra = {"thinking": {"type": "disabled"}}
        return _client(s["deepseek_api_key"], s["deepseek_base_url"]), model, model, extra
    if not s["openai_api_key"]:
        raise RuntimeError("Chave da OpenAI não configurada (Configurações > Modelo de IA).")
    return _client(s["openai_api_key"]), s["openai_model"], _OPENAI_FAST_MODEL, {}


def audio_client() -> OpenAI:
    """Cliente para voz (TTS) e transcrição (STT) — só a OpenAI oferece isso."""
    s = get()
    if not s["openai_api_key"]:
        raise RuntimeError("Voz e transcrição precisam de uma chave da OpenAI (a DeepSeek não tem áudio).")
    return _client(s["openai_api_key"])


def describe_active() -> str:
    """Ex.: 'DeepSeek · deepseek-flash' — para mostrar na UI."""
    s = get()
    if s["llm_provider"] == "deepseek":
        return f"DeepSeek · {resolve_deepseek_model(s['deepseek_model'])}"
    return f"OpenAI · {s['openai_model']}"
