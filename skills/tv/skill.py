"""Skill de TV: "liga/desliga a TV", "coloca na Netflix", "abre o YouTube no fire tv", "HDMI 2",
"aumenta o volume da TV", "muta a TV", "pausa a TV", "volta", "vai pro início"...

Os comandos comuns são reconhecidos direto; o resto passa pelo LLM, que só devolve a ação (JSON).
Quem executa é o cassandra/tv_devices.py (a TV citada no pedido, ou a padrão da aba Aparelhos).
"""
from __future__ import annotations

import json
import re
import unicodedata

from cassandra.openai_client import LLMService
from cassandra.tv_devices import APPS, DeviceError, DeviceManager, find_app, manager as default_manager
from skills.base import Skill


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c)).strip()


_TV = re.compile(r"\b(tv|tvs|televisao|televisor|tele|fire ?tv|firestick|fire stick|roku|hdmi)\b")
_APP_WORDS = re.compile(r"\b(netflix|youtube|prime video|amazon prime|disney|globoplay|hbo|max)\b")
_OPEN = re.compile(r"\b(abre|abrir|abra|coloca|colocar|coloque|bota|botar|poe|liga|ligar|entra|entrar|vai pro|vai para)\b")
_OTHER = re.compile(r"\b(alarme|despertador|timer|temporizador|rotina|lembrete|lista de compras|tarefa|spotify)\b")

_PARSE_SYSTEM = """Você interpreta pedidos para controlar uma TV. Responda APENAS um JSON (sem markdown):
{"action": "power_on|power_off|volume_up|volume_down|mute|channel_up|channel_down|input|app|close_app|up|down|left|right|ok|back|home|menu|play_pause|rewind|forward|help",
 "value": "<app (netflix, youtube, prime, disney, globoplay, max, spotify, twitch) ou número do HDMI, se houver>",
 "times": <quantas vezes repetir, padrão 1; para volume sem número, 3>}"""

_NUMBERS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7,
            "oito": 8, "nove": 9, "dez": 10}


class TvSkill(Skill):
    name = "tv"

    def __init__(self, llm: LLMService, devices: DeviceManager | None = None) -> None:
        self.llm = llm
        self.devices = devices or default_manager

    def can_handle(self, text: str) -> bool:
        t = _norm(text)
        if _OTHER.search(t):
            return False
        if _TV.search(t):
            return True
        return bool(_APP_WORDS.search(t) and _OPEN.search(t))

    def handle(self, text: str) -> str:
        device = self.devices.pick(text)
        if not device:
            return "Nenhuma TV conectada ainda. Conecte a sua na aba Aparelhos."
        intent = self._quick(_norm(text)) or self._parse(text)
        action = intent.get("action") or "help"
        if action == "help":
            return ("Posso ligar e desligar a TV, mudar o volume, abrir Netflix, YouTube e outros apps, trocar o "
                    "HDMI e navegar com as setas.")
        value = intent.get("value")
        times = max(1, min(15, int(intent.get("times") or 1)))
        try:
            result = ""
            for _ in range(times):
                result = self.devices.command(device["id"], action, value)
        except DeviceError as exc:
            return f"Não deu na {device['name']}: {exc}."
        except Exception as exc:  # noqa: BLE001 — TV desligada, rede...
            return f"A {device['name']} não respondeu ({type(exc).__name__})."
        return _reply(action, value, result, device["name"])

    @staticmethod
    def _count(t: str, default: int) -> int:
        m = re.search(r"\b(\d{1,2})\b", t)
        if m:
            return int(m.group(1))
        for word, n in _NUMBERS.items():
            if re.search(rf"\b{word}\b", t):
                return n
        return default

    def _quick(self, t: str) -> dict | None:
        if re.search(r"\bdeslig", t):
            return {"action": "power_off"}
        m = re.search(r"\bhdmi\s*(\d)", t)
        if m:
            return {"action": "input", "value": int(m.group(1))}
        app = find_app(t) if _APP_WORDS.search(t) else None
        if app:
            if re.search(r"\b(fecha|fechar|sai|sair)\b", t):
                return {"action": "close_app", "value": app}
            return {"action": "app", "value": app}
        if re.search(r"\b(liga|ligar|ligue|acende)\b", t):
            return {"action": "power_on"}
        if re.search(r"\b(muta|mutar|silencia|tira o som|sem som|desmuta)\b", t):
            return {"action": "mute"}
        if re.search(r"\b(aumenta|sobe|mais alto|aumentar)\b", t):
            return {"action": "volume_up", "times": self._count(t, 3)}
        if re.search(r"\b(abaixa|diminui|mais baixo|baixa|diminuir)\b", t):
            return {"action": "volume_down", "times": self._count(t, 3)}
        if re.search(r"\b(pausa|pause|continua|play|despausa)\b", t):
            return {"action": "play_pause"}
        if re.search(r"\b(inicio|tela inicial|home)\b", t):
            return {"action": "home"}
        if re.search(r"\b(volta|voltar)\b", t):
            return {"action": "back"}
        return None

    def _parse(self, text: str) -> dict:
        try:
            raw = self.llm.create_completion(
                fast=True, temperature=0, max_tokens=80,
                messages=[{"role": "system", "content": _PARSE_SYSTEM}, {"role": "user", "content": text}],
            ).choices[0].message.content or "{}"
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                return json.loads(m.group())
        except Exception:  # noqa: BLE001
            pass
        return {"action": "help"}


def _reply(action: str, value, result: str, name: str) -> str:
    if action == "app":
        key = find_app(str(value or ""))
        return f"Abrindo {APPS[key]['label'] if key else value} na {name}."
    return {
        "power_on": f"Ligando a {name}.", "power_off": f"Desligando a {name}.",
        "volume_up": "Volume da TV aumentado.", "volume_down": "Volume da TV diminuído.",
        "mute": "Som da TV alternado.", "input": f"{result} na {name}.",
        "play_pause": "Feito.", "home": "Tela inicial.", "back": "Voltei.", "close_app": "App fechado.",
    }.get(action, "Feito.")
