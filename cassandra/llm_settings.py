"""Configuração runtime do LLM: provider ativo (openai | deepseek) + modelo + chave de cada um.

Editável pela UI (Configurações > Modelo de IA, rota /api/llm) sem reiniciar — cada chamada do LLMService
pergunta aqui qual provider usar. Começa com os valores do .env (LLM_PROVIDER, OPENAI_API_KEY, OPENAI_MODEL,
DEEPSEEK_API_KEY, DEEPSEEK_MODEL) e o que for salvo pela UI vai para data/llm_settings.json, que passa a ter
prioridade sobre o .env. Esse arquivo guarda chaves: fica fora do git (.gitignore).

Mesmo desenho do settings_store.py do orchestrator e do llm_settings.py do editor.

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

PROVIDERS = ("openai", "deepseek")

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
        # Voz e microfone dependem da OpenAI, qualquer que seja o provider do chat.
        "audio_available": bool(s["openai_api_key"]),
    }


def update(fields: dict[str, Any]) -> dict[str, Any]:
    provider = fields.get("llm_provider")
    if provider is not None and provider not in PROVIDERS:
        raise ValueError(f"llm_provider inválido: {provider!r} (use openai ou deepseek)")
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


def _client(api_key: str, base_url: str = "") -> OpenAI:
    key = (api_key, base_url)
    with _lock:
        client = _clients.get(key)
        if client is None:
            kwargs: dict[str, Any] = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            client = _clients[key] = OpenAI(**kwargs)
        return client


def chat_client() -> tuple[OpenAI, str, str, dict[str, Any]]:
    """(cliente, modelo principal, modelo rápido, extra_body) do provider ativo agora."""
    s = get()
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
