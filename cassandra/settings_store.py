"""Persistent UI/runtime settings store backed by data/ui_settings.json."""
from __future__ import annotations

import json
from pathlib import Path

_DEFAULTS: dict = {
    "modules": {
        "chat": True,
        "shopping": True,
        "todos": True,
        "alarms": True,
    },
    "voice": {
        "enabled": True,
        "tts_model": "tts-1",
        "tts_voice": "nova",
        "fallback_lang": "pt",
        "fallback_rate": 160,
    },
    "sounds": {
        "enabled": True,
    },
    "session": {
        "wake_timeout": 30,
    },
}


class SettingsStore:
    def __init__(self, path: str = "data/ui_settings.json") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    def get(self) -> dict:
        return _deep_copy(self._data)

    def update(self, patch: dict) -> dict:
        self._data = _deep_merge(self._data, patch)
        self._save()
        return self.get()

    def reset(self) -> dict:
        self._data = _deep_copy(_DEFAULTS)
        self._save()
        return self.get()

    def _load(self) -> dict:
        if not self._path.exists():
            return _deep_copy(_DEFAULTS)
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return _deep_copy(_DEFAULTS)
            return _deep_merge(_deep_copy(_DEFAULTS), raw)
        except (OSError, json.JSONDecodeError):
            return _deep_copy(_DEFAULTS)

    def _save(self) -> None:
        try:
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass


def _deep_copy(d: dict) -> dict:
    return json.loads(json.dumps(d))


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result
