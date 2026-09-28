"""Registro de gastos (cassandra/usage_log.py)."""
import json
import types
from datetime import datetime

from cassandra import usage_log as ul


def _usage(p, c, cached=0):
    return types.SimpleNamespace(prompt_tokens=p, completion_tokens=c,
                                 prompt_tokens_details=types.SimpleNamespace(cached_tokens=cached))


def _capture(monkeypatch, tmp_path):
    monkeypatch.setattr(ul, "LOG_PATH", tmp_path / "usage.jsonl")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)


def test_llm_cost_uses_price_table_and_cached_tokens(monkeypatch, tmp_path):
    _capture(monkeypatch, tmp_path)
    ul.record_llm("openai", "gpt-4o-mini", _usage(1_000_000, 1_000_000, cached=500_000))
    row = json.loads((tmp_path / "usage.jsonl").read_text(encoding="utf-8"))
    assert abs(row["cost"] - (0.5 * 0.15 + 0.5 * 0.075 + 0.60)) < 1e-9
    ul.record_llm("local", "qwen3:1.7b", None)
    ul.record_llm("openai", "modelo-novo", _usage(10, 10))
    s = ul.summary(7)
    assert s["unpriced"] == ["modelo-novo"]
    assert abs(s["totals"]["today"] - row["cost"]) < 1e-6


def test_tts_stt_and_cache(monkeypatch, tmp_path):
    _capture(monkeypatch, tmp_path)
    ul.record_tts("openai", "gpt-4o-mini-tts", 100, seconds=60)
    ul.record_tts("openai", "gpt-4o-mini-tts", 100, cached=True)
    ul.record_stt("openai", "gpt-4o-mini-transcribe", 120)
    s = ul.summary(7)
    assert abs(s["totals"]["today"] - (0.015 + 0.006)) < 1e-9
    assert s["cache"]["hits"] == 1 and s["cache"]["chars"] == 100


def test_azure_free_tier_is_free_until_the_quota(monkeypatch, tmp_path):
    _capture(monkeypatch, tmp_path)
    monkeypatch.setattr(ul, "AZURE_FREE_TIER", True)
    monkeypatch.setattr(ul, "AZURE_FREE", {"tts_chars": 1000, "stt_seconds": 60})
    ul.record_tts("azure", "pt-BR-ElzaNeural", 800)
    ul.record_tts("azure", "pt-BR-ElzaNeural", 400)  # 200 passam da cota
    s = ul.summary(7)
    assert abs(s["totals"]["today"] - 200 * 15 / 1_000_000) < 1e-12
    assert s["azure"]["tts_chars"] == 1200


def test_nothing_is_written_during_tests(monkeypatch, tmp_path):
    monkeypatch.setattr(ul, "LOG_PATH", tmp_path / "usage.jsonl")
    ul.record_stt("openai", "whisper-1", 10)
    assert not (tmp_path / "usage.jsonl").exists()
