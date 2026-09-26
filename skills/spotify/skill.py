"""Skill do Spotify: tocar música, artista, álbum, playlist (sua ou pública), curtidas, gênero/clima,
pausar, continuar, pular, voltar, volume da música, aleatório, repetir, fila, "que música é essa", curtir.

Comandos simples (pausa, próxima...) são reconhecidos direto; pedidos de tocar/enfileirar passam pelo LLM,
que só extrai o que tocar (JSON) — a busca e o play são na Web API (cassandra/spotify.py).
"""
from __future__ import annotations

import json
import random
import re
import unicodedata
from difflib import SequenceMatcher

from cassandra.openai_client import LLMService
from cassandra.spotify import SpotifyClient, SpotifyError, client as default_client
from skills.base import Skill


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c)).strip()


# Palavras que, sozinhas, já indicam música/Spotify.
_STRONG = re.compile(
    r"\b(spotify|musica|musicas|playlist|playlists|album|albuns|faixa|cancao|cancoes|"
    r"pra tocar|para tocar|tocando)\b")
# Verbos de tocar (sem "coloca" solto: "coloca leite na lista" é da lista de compras).
_PLAY = re.compile(r"\b(toca|toque|tocar|toca ai|bota pra tocar|poe pra tocar|coloca pra tocar|solta o som|"
                   r"quero ouvir|me deixa ouvir|reproduz|reproduza|play)\b")
# Controles (valem sem a palavra "música").
_CONTROLS = re.compile(
    r"\b(pausa|pause|pausar|despausa|despausar|continua|continuar|retoma|retomar|volta a tocar|"
    r"proxima|pula|pular|avanca|anterior|volta a musica|musica anterior|"
    r"que musica|qual musica|que som e esse|quem canta|o que (esta|ta) tocando|"
    r"aleatorio|embaralha|shuffle|repete|repetir|repeticao|curti|curtir|gostei dessa|salva essa|"
    r"descurtir|fila)\b")
# Pedidos que são de outras skills.
_OTHER = re.compile(r"\b(alarme|despertador|timer|temporizador|cronometro|rotina|lembrete|lista de compras|tarefa)\b")

_PARSE_SYSTEM = """Você interpreta pedidos de música para uma assistente que controla o Spotify.
Responda APENAS com um JSON (sem markdown), um destes:
{"action":"play","kind":"track|artist|album|playlist|my_playlist|liked|genre|top","query":"...","artist":"..."}
{"action":"queue","kind":"track|album","query":"...","artist":"..."}
{"action":"pause"} {"action":"resume"} {"action":"next"} {"action":"previous"}
{"action":"volume","level":0-100} {"action":"volume","delta":10 ou -10}
{"action":"shuffle","on":true|false} {"action":"repeat","mode":"track|context|off"}
{"action":"now_playing"} {"action":"save"} {"action":"unsave"} {"action":"help"}
Regras:
- "toca/coloca X" com nome de música -> kind track (query = nome da música, artist = cantor se dito).
- só cantor/banda ("toca Legião Urbana", "coloca algo do Queen") -> kind artist, query = o artista.
- "o álbum X" -> album. "a playlist X"/"minha playlist X" -> my_playlist (query = nome da playlist).
- "minhas músicas curtidas"/"minhas favoritas" -> liked. "o que eu mais ouço"/"minhas mais tocadas" -> top.
- gênero, clima ou ocasião ("um rock", "música pra relaxar", "sertanejo", "lo-fi pra estudar") -> genre,
  query = termo de busca curto em português ou inglês.
- "toca música"/"coloca um som" sem dizer o quê -> top.
- "mais alto/aumenta a música" -> volume delta 10; "mais baixo/abaixa a música" -> delta -10.
- Corrija nomes mal transcritos por voz quando for óbvio (ex.: "legiao urbana" -> "Legião Urbana")."""

_HELP = ("Posso tocar uma música, um artista, um álbum, uma playlist sua ou um estilo, e também pausar, "
         "continuar, pular, voltar, mudar o volume da música, deixar no aleatório, repetir, "
         "pôr na fila, dizer o que está tocando e curtir a música.")


class SpotifySkill(Skill):
    name = "spotify"

    def __init__(self, llm: LLMService, spotify: SpotifyClient | None = None) -> None:
        self.llm = llm
        self.sp = spotify or default_client

    # ── roteamento ──
    def can_handle(self, text: str) -> bool:
        t = _norm(text)
        if _OTHER.search(t):
            return False
        if _STRONG.search(t) or _PLAY.search(t):
            return True
        if _CONTROLS.search(t) and len(t.split()) <= 8:  # "continua", "pula"... só em frases curtas
            return True
        return False

    def handle(self, text: str) -> str:
        if not self.sp.configured:
            return "O Spotify ainda não está configurado: falta o SPOTIFY_CLIENT_ID no .env."
        if not self.sp.connected:
            return "Conecte sua conta do Spotify em Configurações, no card Spotify, e eu toco o que você pedir."
        intent = self.intent(text)
        try:
            return self._run(intent)
        except SpotifyError as exc:
            return str(exc)

    # ── entendimento ──
    def intent(self, text: str) -> dict:
        return self._quick_intent(_norm(text)) or self._parse(text)

    @staticmethod
    def _quick_intent(t: str) -> dict | None:
        words = t.split()
        if len(words) > 7:
            return None
        if re.search(r"\b(despausa|despausar|continua|continuar|retoma|retomar|volta a tocar)\b", t):
            return {"action": "resume"}
        if re.search(r"\b(pausa|pause|pausar)\b", t) or re.search(r"\b(para|pare|desliga)\b.*\bmusica\b", t):
            return {"action": "pause"}
        if re.search(r"\b(proxima|pula|pular|avanca)\b", t):
            return {"action": "next"}
        if re.search(r"\b(anterior|volta a musica|volta uma)\b", t):
            return {"action": "previous"}
        if re.search(r"\b(que musica|qual musica|que som e esse|quem canta|o que (esta|ta) tocando)\b", t):
            return {"action": "now_playing"}
        if re.search(r"\b(descurtir|tira das curtidas)\b", t):
            return {"action": "unsave"}
        if re.search(r"\b(curti|curtir|gostei dessa|salva essa)\b", t):
            return {"action": "save"}
        return None

    def _parse(self, text: str) -> dict:
        try:
            raw = self.llm.create_completion(
                fast=True, temperature=0, max_tokens=120,
                messages=[{"role": "system", "content": _PARSE_SYSTEM}, {"role": "user", "content": text}],
            ).choices[0].message.content or "{}"
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                return json.loads(m.group())
        except Exception:  # noqa: BLE001 — sem LLM, tenta um palpite simples
            pass
        t = _norm(text)
        query = re.sub(r"^.*?\b(toca|toque|tocar|coloca|bota|poe|quero ouvir)\b\s*", "", t).strip()
        return {"action": "play", "kind": "track" if query else "top", "query": query}

    # ── execução ──
    def _run(self, it: dict) -> str:
        action = it.get("action")
        if action == "play":
            return self._play(it)
        if action == "queue":
            return self._queue(it)
        if action == "pause":
            self.sp.pause()
            return "Pausei."
        if action == "resume":
            self.sp.resume()
            return "Continuando."
        if action == "next":
            self.sp.next()
            return "Próxima."
        if action == "previous":
            self.sp.previous()
            return "Voltei uma."
        if action == "volume":
            if "level" in it:
                return f"Volume da música em {self.sp.set_volume(int(it['level']))}%."
            current = self.sp.volume()
            if current is None:
                return "Nada tocando no Spotify agora."
            return f"Volume da música em {self.sp.set_volume(current + int(it.get('delta', 10)))}%."
        if action == "shuffle":
            on = bool(it.get("on", True))
            self.sp.shuffle(on)
            return "Aleatório ligado." if on else "Aleatório desligado."
        if action == "repeat":
            mode = it.get("mode", "context")
            mode = mode if mode in ("track", "context", "off") else "context"
            self.sp.repeat(mode)
            return {"track": "Repetindo esta música.", "context": "Repetindo.", "off": "Sem repetir."}[mode]
        if action == "now_playing":
            state = self.sp.playback()
            if not state or not state.get("item"):
                return "Nada tocando no Spotify agora."
            item = state["item"]
            return f"Está tocando {item.get('name')}, de {_artists(item)}."
        if action in ("save", "unsave"):
            state = self.sp.playback()
            if not state or not state.get("item"):
                return "Nada tocando no Spotify agora."
            self.sp.save_track(state["item"], save=action == "save")
            name = state["item"].get("name")
            return f"{name} salva nas suas curtidas." if action == "save" else f"{name} saiu das curtidas."
        return _HELP

    def _play(self, it: dict) -> str:
        kind = it.get("kind") or "track"
        query = (it.get("query") or "").strip()
        artist = (it.get("artist") or "").strip()

        if kind == "liked":
            tracks = self.sp.liked_tracks(50)
            if not tracks:
                return "Você ainda não tem músicas curtidas."
            random.shuffle(tracks)
            dev = self.sp.play(uris=[t["uri"] for t in tracks])
            return f"Tocando suas músicas curtidas{_where(dev, self.sp)}."
        if kind == "top" or (not query and kind != "my_playlist"):
            tracks = self.sp.top_tracks(30) or self.sp.liked_tracks(50)
            if not tracks:
                return "Ainda não sei do que você gosta. Me diga uma música, um artista ou um estilo."
            random.shuffle(tracks)
            dev = self.sp.play(uris=[t["uri"] for t in tracks])
            return f"Tocando as que você mais ouve{_where(dev, self.sp)}."
        if kind == "artist":
            found = self.sp.search(query, "artist", 5)
            if not found:
                return f"Não achei o artista {query} no Spotify."
            best = _best(found, query)
            dev = self.sp.play(context_uri=best["uri"])
            return f"Tocando {best['name']}{_where(dev, self.sp)}."
        if kind == "album":
            q = f"{query} {artist}".strip()
            found = self.sp.search(q, "album", 5)
            if not found:
                return f"Não achei o álbum {query}."
            best = _best(found, query)
            dev = self.sp.play(context_uri=best["uri"])
            return f"Tocando o álbum {best['name']}, de {_artists(best)}{_where(dev, self.sp)}."
        if kind in ("playlist", "my_playlist"):
            mine = self.sp.my_playlists()
            if query:
                scored = sorted(mine, key=lambda p: _similar(p.get("name", ""), query), reverse=True)
                if scored and _similar(scored[0].get("name", ""), query) >= 0.6:
                    dev = self.sp.play(context_uri=scored[0]["uri"])
                    return f"Tocando sua playlist {scored[0]['name']}{_where(dev, self.sp)}."
                if kind == "my_playlist" and not mine:
                    return "Não achei playlists na sua conta."
                return self._play_search_playlist(query)
            return "Qual playlist?"
        if kind == "genre":
            return self._play_search_playlist(query, fallback_tracks=True)

        # track
        q = f"{query} {artist}".strip()
        found = self.sp.search(q, "track", 5)
        if not found and artist:
            found = self.sp.search(query, "track", 5)
        if not found:
            return f"Não achei {query} no Spotify."
        best = _best(found, query, artist)
        dev = self.sp.play(uris=[best["uri"]])
        return f"Tocando {best['name']}, de {_artists(best)}{_where(dev, self.sp)}."

    def _play_search_playlist(self, query: str, fallback_tracks: bool = True) -> str:
        playlists = self.sp.search(query, "playlist", 5)
        for pl in playlists:
            try:
                dev = self.sp.play(context_uri=pl["uri"])
                return f"Tocando a playlist {pl['name']}{_where(dev, self.sp)}."
            except SpotifyError as exc:
                if exc.status in (403, 404) and exc.reason != "NO_DEVICE":
                    continue  # playlist indisponível para o app: tenta a próxima
                raise
        if fallback_tracks:
            tracks = self.sp.search(query, "track", 10)
            if tracks:
                random.shuffle(tracks)
                dev = self.sp.play(uris=[t["uri"] for t in tracks])
                return f"Tocando músicas de {query}{_where(dev, self.sp)}."
        return f"Não achei nada de {query} no Spotify."

    def _queue(self, it: dict) -> str:
        q = f"{it.get('query', '')} {it.get('artist', '')}".strip()
        if not q:
            return "O que você quer pôr na fila?"
        found = self.sp.search(q, "track", 5)
        if not found:
            return f"Não achei {q} no Spotify."
        best = _best(found, it.get("query", ""), it.get("artist", ""))
        self.sp.queue(best["uri"])
        return f"{best['name']}, de {_artists(best)}, vai tocar em seguida."


def _artists(item: dict) -> str:
    return ", ".join(a.get("name", "") for a in item.get("artists", [])) or "artista desconhecido"


def _similar(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if b in a or a in b:
        return 0.9
    return SequenceMatcher(None, a, b).ratio()


def _best(items: list[dict], query: str, artist: str = "") -> dict:
    """O resultado da busca que mais bate com o nome (e o artista, se dito); empate: a ordem do Spotify."""
    def score(pair):
        idx, item = pair
        s = _similar(item.get("name", ""), query) if query else 0
        if artist:
            s += max((_similar(a.get("name", ""), artist) for a in item.get("artists", [])), default=0)
        return s - idx * 0.05
    return max(enumerate(items), key=score)[1]


def _where(device: dict, sp: SpotifyClient) -> str:
    name = device.get("name") or ""
    return "" if name.lower() == sp.device_name.lower() else f" no {name}"
