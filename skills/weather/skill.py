from __future__ import annotations

import requests

from skills.base import Skill


class WeatherSkill(Skill):
    name = "weather"

    def __init__(self, default_city: str = "Sao Paulo") -> None:
        self.default_city = default_city

    def can_handle(self, text: str) -> bool:
        lowered = text.lower()
        keywords = ["tempo", "clima", "temperatura", "previsao"]
        return any(word in lowered for word in keywords)

    def handle(self, text: str) -> str:
        city = self._extract_city(text) or self.default_city
        try:
            response = requests.get(f"https://wttr.in/{city}?format=3", timeout=8)
            response.raise_for_status()
            return response.text.strip()
        except requests.RequestException:
            return "Nao consegui consultar o tempo agora. Tente novamente em instantes."

    def _extract_city(self, text: str) -> str | None:
        lowered = text.lower()
        if " em " in lowered:
            return text[lowered.rfind(" em ") + 4 :].strip()
        return None
