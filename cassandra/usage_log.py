"""Registro do que a Cassandra gasta nas APIs pagas: texto (LLM), voz (TTS) e transcrição (STT).

Cada chamada vira uma linha em data/usage_log.jsonl (fora do git): quando, tipo, provedor, modelo, quantidade
(tokens, caracteres ou segundos de áudio) e o custo estimado em US$ pela tabela de preços abaixo. A aba Gastos
da UI lê summary().

Preços: tabela pública de cada provedor (US$), sem impostos. Frase tocada do cache da voz entra com custo 0 —
mostra quanto o cache economiza. O Azure no plano gratuito (F0) tem cota mensal: dentro dela o custo é 0.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

LOG_PATH = Path("data/usage_log.jsonl")
_lock = threading.Lock()

# US$ por 1 milhão de tokens: (entrada, entrada em cache, saída)
LLM_PRICES: dict[str, tuple[float, float, float]] = {
    "gpt-4o-mini": (0.15, 0.075, 0.60),
    "gpt-4o": (2.50, 1.25, 10.00),
    "gpt-4.1": (2.00, 0.50, 8.00),
    "gpt-4.1-mini": (0.40, 0.10, 1.60),
    "gpt-4.1-nano": (0.10, 0.025, 0.40),
    "gpt-5": (1.25, 0.125, 10.00),
    "gpt-5-mini": (0.25, 0.025, 2.00),
    "gpt-5-nano": (0.05, 0.005, 0.40),
    "gpt-5.1": (1.25, 0.125, 10.00),
    "deepseek-flash": (0.28, 0.028, 0.42),
    "deepseek-chat": (0.28, 0.028, 0.42),
}
# Voz: US$ por 1 milhão de caracteres (tts-1, Azure neural) ou por minuto de áudio gerado (gpt-4o-mini-tts).
TTS_PER_M_CHARS = {"tts-1": 15.0, "tts-1-hd": 30.0, "azure": 15.0}
TTS_PER_MINUTE = {"gpt-4o-mini-tts": 0.015}
# Transcrição: US$ por minuto de áudio.
STT_PER_MINUTE = {"gpt-4o-mini-transcribe": 0.003, "gpt-4o-transcribe": 0.006, "whisper-1": 0.006, "azure": 1.0 / 60}
# Plano gratuito do Azure (F0), por mês.
AZURE_FREE = {"tts_chars": 500_000, "stt_seconds": 5 * 3600}
AZURE_FREE_TIER = os.getenv("AZURE_SPEECH_TIER", "F0").strip().upper() != "S0"

KINDS = {"llm": "Texto", "tts": "Voz", "stt": "Transcrição"}


def _price_llm(model: str, prompt: int, cached: int, completion: int) -> float | None:
    price = LLM_PRICES.get(model) or next((p for m, p in LLM_PRICES.items() if model.startswith(m + "-")), None)
    if price is None:
        return None
    return ((prompt - cached) * price[0] + cached * price[1] + completion * price[2]) / 1_000_000


def _write(row: dict[str, Any]) -> None:
    if os.getenv("PYTEST_CURRENT_TEST"):
        return  # os testes não sujam o registro de verdade
    row = {"ts": datetime.now().isoformat(timespec="seconds"), **row}
    try:
        with _lock:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass  # registrar gasto nunca pode derrubar uma resposta


# ── Registro ────────────────────────────────────────────────────────────────

def record_llm(provider: str, model: str, usage: Any, purpose: str = "") -> None:
    """usage = objeto usage da resposta (OpenAI/DeepSeek). Sem usage (modelo local), só conta a chamada."""
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(usage, "completion_tokens", 0) or 0)
    details = getattr(usage, "prompt_tokens_details", None)
    cached = int(getattr(details, "cached_tokens", 0) or 0) if details else 0
    cached = cached or int(getattr(usage, "prompt_cache_hit_tokens", 0) or 0)  # DeepSeek
    cost = 0.0 if provider == "local" else _price_llm(model, prompt, cached, completion)
    _write({"kind": "llm", "provider": provider, "model": model, "purpose": purpose, "prompt_tokens": prompt,
            "cached_tokens": cached, "completion_tokens": completion, "cost": cost})


def record_tts(provider: str, model: str, chars: int, seconds: float | None = None, cached: bool = False) -> None:
    if cached:
        cost = 0.0
    elif model in TTS_PER_MINUTE and seconds is not None:
        cost = seconds / 60 * TTS_PER_MINUTE[model]
    elif model in TTS_PER_MINUTE:
        cost = chars / 15 / 60 * TTS_PER_MINUTE[model]  # ~15 caracteres por segundo de fala
    else:
        per_m = TTS_PER_M_CHARS.get("azure" if provider == "azure" else model)
        cost = None if per_m is None else chars * per_m / 1_000_000
    _write({"kind": "tts", "provider": provider, "model": model, "chars": chars,
            "seconds": round(seconds, 2) if seconds is not None else None, "cached": cached, "cost": cost})


def record_stt(provider: str, model: str, seconds: float) -> None:
    per_min = STT_PER_MINUTE.get("azure" if provider == "azure" else model)
    cost = 0.0 if provider == "local" else (None if per_min is None else seconds / 60 * per_min)
    _write({"kind": "stt", "provider": provider, "model": model, "seconds": round(seconds, 2), "cost": cost})


def wav_seconds(path: str) -> float:
    import wave  # noqa: PLC0415

    try:
        with wave.open(path, "rb") as wf:
            return wf.getnframes() / float(wf.getframerate() or 16000)
    except Exception:  # noqa: BLE001
        return 0.0


# ── Leitura ─────────────────────────────────────────────────────────────────

def _rows(since: date) -> list[dict[str, Any]]:
    out = []
    try:
        with LOG_PATH.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("ts", "")[:10] >= since.isoformat():
                    out.append(row)
    except FileNotFoundError:
        pass
    return out


def _apply_azure_free_tier(rows: list[dict[str, Any]]) -> None:
    """No F0 o Azure não cobra dentro da cota do mês: zera o custo dessas linhas (e só cobra o que passar)."""
    if not AZURE_FREE_TIER:
        return
    used: dict[tuple[str, str], float] = defaultdict(float)  # (mês, tipo) -> já usado
    for row in rows:
        if row.get("provider") != "azure" or row.get("cached"):
            continue
        month = row["ts"][:7]
        if row["kind"] == "tts":
            amount, free = row.get("chars") or 0, AZURE_FREE["tts_chars"]
        elif row["kind"] == "stt":
            amount, free = row.get("seconds") or 0, AZURE_FREE["stt_seconds"]
        else:
            continue
        before = used[(month, row["kind"])]
        used[(month, row["kind"])] += amount
        paid = max(0.0, before + amount - free) - max(0.0, before - free)
        if row.get("cost"):
            row["cost"] = row["cost"] * (paid / amount if amount else 0)


def summary(days: int = 30) -> dict[str, Any]:
    today = date.today()
    first_month = today.replace(day=1)
    since = min(today - timedelta(days=days - 1), first_month)
    rows = _rows(since)
    _apply_azure_free_tier(rows)

    labels = [(today - timedelta(days=days - 1 - i)).isoformat() for i in range(days)]
    daily = {k: {d: 0.0 for d in labels} for k in KINDS}
    by_model: dict[tuple[str, str, str], dict[str, Any]] = {}
    totals = {"period": 0.0, "today": 0.0, "month": 0.0}
    cache = {"hits": 0, "chars": 0, "saved": 0.0}
    azure = {"tts_chars": 0, "stt_seconds": 0.0}
    unpriced = set()
    for row in rows:
        day, kind, cost = row["ts"][:10], row.get("kind"), row.get("cost")
        if kind not in KINDS:
            continue
        if row["ts"][:7] == today.isoformat()[:7] and row.get("provider") == "azure" and not row.get("cached"):
            if kind == "tts":
                azure["tts_chars"] += row.get("chars") or 0
            elif kind == "stt":
                azure["stt_seconds"] += row.get("seconds") or 0
        if kind == "tts" and row.get("cached"):
            cache["hits"] += 1
            cache["chars"] += row.get("chars") or 0
            continue
        if cost is None:
            unpriced.add(row.get("model") or "?")
            cost = 0.0
        if day >= first_month.isoformat():
            totals["month"] += cost
        if day == today.isoformat():
            totals["today"] += cost
        if day in daily[kind]:
            daily[kind][day] += cost
            totals["period"] += cost
            key = (kind, row.get("provider") or "", row.get("model") or "")
            item = by_model.setdefault(key, {"kind": kind, "provider": key[1], "model": key[2], "calls": 0,
                                             "cost": 0.0, "tokens_in": 0, "tokens_out": 0, "chars": 0,
                                             "seconds": 0.0})
            item["calls"] += 1
            item["cost"] += cost
            item["tokens_in"] += row.get("prompt_tokens") or 0
            item["tokens_out"] += row.get("completion_tokens") or 0
            item["chars"] += row.get("chars") or 0
            item["seconds"] += row.get("seconds") or 0
    # Economia do cache: quanto essas frases custariam na voz em uso (estimativa pelo preço do Azure/tts-1).
    cache["saved"] = cache["chars"] * TTS_PER_M_CHARS["azure"] / 1_000_000
    days_in_month = today.day
    return {
        "days": labels,
        "daily": {k: [round(v, 6) for v in daily[k].values()] for k in KINDS},
        "kinds": KINDS,
        "totals": {k: round(v, 6) for k, v in totals.items()},
        "month_projection": round(totals["month"] / days_in_month * 30, 4) if days_in_month else 0,
        "by_model": sorted(by_model.values(), key=lambda i: -i["cost"]),
        "cache": {**cache, "saved": round(cache["saved"], 6)},
        "azure": {**azure, "free_tier": AZURE_FREE_TIER, "tts_free": AZURE_FREE["tts_chars"],
                  "stt_free": AZURE_FREE["stt_seconds"]},
        "unpriced": sorted(unpriced),
        "generated": time.time(),
    }
