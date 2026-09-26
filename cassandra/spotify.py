"""Cliente da Web API do Spotify: login da conta (OAuth com PKCE, sem client secret) e controle do que toca.

Quem toca de fato é o dispositivo Spotify Connect "Cassandra" (librespot, serviço cassandra-spotify no Pi);
daqui só se manda tocar, pausar, pular, buscar... Só a biblioteca padrão do Python.

Configuração (.env):
  SPOTIFY_CLIENT_ID      o Client ID do app no Spotify for Developers (obrigatório)
  SPOTIFY_REDIRECT_URI   padrão https://cassandra-rafaelkrueger.netlify.app/api/spotify/callback
  SPOTIFY_LOCAL_REDIRECT_URI  padrão http://127.0.0.1:8080/api/spotify/callback (quando a UI é aberta no próprio Pi)
  SPOTIFY_DEVICE_NAME    padrão Cassandra
Os dois redirect URIs precisam estar cadastrados no app. O token fica em data/spotify_token.json (fora do git).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"
SCOPES = " ".join([
    "user-read-playback-state", "user-modify-playback-state", "user-read-currently-playing",
    "user-library-read", "user-library-modify", "playlist-read-private", "playlist-read-collaborative",
    "user-read-private", "user-read-recently-played", "user-top-read",
])
TOKEN_FILE = Path("data/spotify_token.json")


class SpotifyError(Exception):
    def __init__(self, message: str, status: int = 0, reason: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.reason = reason


class SpotifyClient:
    def __init__(self) -> None:
        self.client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
        self.redirect_uri = os.getenv(
            "SPOTIFY_REDIRECT_URI", "https://cassandra-rafaelkrueger.netlify.app/api/spotify/callback").strip()
        self.local_redirect_uri = os.getenv(
            "SPOTIFY_LOCAL_REDIRECT_URI", "http://127.0.0.1:8080/api/spotify/callback").strip()
        self.device_name = os.getenv("SPOTIFY_DEVICE_NAME", "Cassandra").strip() or "Cassandra"
        self._lock = threading.Lock()
        self._pending: dict[str, tuple[str, str, float]] = {}  # state -> (verifier, redirect_uri, expira)
        self._token: dict[str, Any] | None = self._load_token()
        self._me: dict[str, Any] | None = None

    # ── estado ──
    @property
    def configured(self) -> bool:
        return bool(self.client_id)

    @property
    def connected(self) -> bool:
        return bool(self._token and self._token.get("refresh_token"))

    @staticmethod
    def _load_token() -> dict[str, Any] | None:
        try:
            return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _save_token(self, token: dict[str, Any]) -> None:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(json.dumps(token), encoding="utf-8")
        try:
            os.chmod(TOKEN_FILE, 0o600)
        except OSError:
            pass
        self._token = token

    def disconnect(self) -> None:
        with self._lock:
            self._token = None
            self._me = None
            TOKEN_FILE.unlink(missing_ok=True)

    # ── login (Authorization Code + PKCE) ──
    def login_url(self, origin: str = "") -> str:
        if not self.configured:
            raise SpotifyError("SPOTIFY_CLIENT_ID não configurado no .env.")
        redirect = self.local_redirect_uri if origin.startswith(("http://127.0.0.1", "http://localhost")) \
            else self.redirect_uri
        verifier = secrets.token_urlsafe(64)[:96]
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)
        now = time.time()
        self._pending = {k: v for k, v in self._pending.items() if v[2] > now}
        self._pending[state] = (verifier, redirect, now + 600)
        return AUTH_URL + "?" + urllib.parse.urlencode({
            "client_id": self.client_id, "response_type": "code", "redirect_uri": redirect,
            "code_challenge_method": "S256", "code_challenge": challenge, "state": state, "scope": SCOPES,
        })

    def finish_login(self, code: str, state: str) -> None:
        pending = self._pending.pop(state, None)
        if not pending or pending[2] < time.time():
            raise SpotifyError("Login expirado ou inválido — tente conectar de novo.")
        verifier, redirect, _ = pending
        token = self._token_request({
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect,
            "client_id": self.client_id, "code_verifier": verifier,
        })
        token["authorized_at"] = time.time()  # o refresh token vale 180 dias a partir daqui (modo dev)
        self._save_token(token)
        self._me = None

    def _token_request(self, form: dict[str, str]) -> dict[str, Any]:
        req = urllib.request.Request(
            TOKEN_URL, data=urllib.parse.urlencode(form).encode(), method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:200]
            raise SpotifyError(f"Spotify recusou o login ({exc.code}): {detail}", exc.code) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise SpotifyError(f"Sem conexão com o Spotify: {exc}") from exc
        data["expires_at"] = time.time() + int(data.get("expires_in", 3600)) - 60
        if self._token:
            if not data.get("refresh_token"):
                data["refresh_token"] = self._token.get("refresh_token")
            if self._token.get("authorized_at"):
                data["authorized_at"] = self._token["authorized_at"]
        return data

    def _access_token(self) -> str:
        with self._lock:
            if not self.connected:
                raise SpotifyError("A conta do Spotify ainda não foi conectada (Configurações > Spotify).")
            if time.time() >= float(self._token.get("expires_at", 0)):
                try:
                    token = self._token_request({
                        "grant_type": "refresh_token", "refresh_token": self._token["refresh_token"],
                        "client_id": self.client_id,
                    })
                except SpotifyError as exc:
                    if exc.status in (400, 401):
                        raise SpotifyError("O login do Spotify expirou — conecte a conta de novo "
                                           "(Configurações > Spotify).", exc.status, "EXPIRED") from exc
                    raise
                self._save_token(token)
            return self._token["access_token"]

    # ── chamadas ──
    def api(self, method: str, path: str, params: dict | None = None, body: Any = None, _retry: bool = True) -> Any:
        url = API + path
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        data = json.dumps(body).encode() if body is not None else (b"" if method in ("PUT", "POST") else None)
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self._access_token()}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                return json.loads(raw) if raw.strip() else None
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode(errors="replace")
            try:
                err = json.loads(raw).get("error", {})
            except ValueError:
                err = {}
            message = err.get("message", raw[:150]) if isinstance(err, dict) else str(err)
            reason = err.get("reason", "") if isinstance(err, dict) else ""
            if exc.code == 401 and _retry:
                with self._lock:
                    if self._token:
                        self._token["expires_at"] = 0  # força renovar
                return self.api(method, path, params, body, _retry=False)
            if exc.code == 429:
                raise SpotifyError("O Spotify pediu para esperar um pouco (muitas chamadas).", 429) from exc
            raise SpotifyError(message or f"erro {exc.code}", exc.code, reason) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise SpotifyError(f"Sem conexão com o Spotify: {exc}") from exc

    def me(self) -> dict[str, Any]:
        if self._me is None:
            self._me = self.api("GET", "/me") or {}
        return self._me

    # ── dispositivos ──
    def devices(self) -> list[dict[str, Any]]:
        return (self.api("GET", "/me/player/devices") or {}).get("devices", [])

    def pick_device(self) -> dict[str, Any]:
        """O dispositivo "Cassandra" (o Pi); sem ele, o que estiver ativo agora."""
        devices = self.devices()
        wanted = self.device_name.lower()
        for dev in devices:
            if (dev.get("name") or "").lower() == wanted:
                return dev
        for dev in devices:
            if dev.get("is_active"):
                return dev
        raise SpotifyError(
            f"Não achei o dispositivo {self.device_name} no Spotify. Abra o app do Spotify no celular, "
            f"no mesmo Wi-Fi, e escolha {self.device_name} na lista de dispositivos uma vez.", 404, "NO_DEVICE")

    # ── tocar ──
    def play(self, uris: list[str] | None = None, context_uri: str | None = None,
             offset: dict | None = None) -> dict[str, Any]:
        device = self.pick_device()
        body: dict[str, Any] = {}
        if context_uri:
            body["context_uri"] = context_uri
        if uris:
            body["uris"] = uris
        if offset:
            body["offset"] = offset
        try:
            self.api("PUT", "/me/player/play", {"device_id": device["id"]}, body or None)
        except SpotifyError as exc:
            if exc.status != 404:
                raise self._friendly(exc) from exc
            # dispositivo "dormindo": transfere e tenta de novo
            self.api("PUT", "/me/player", body={"device_ids": [device["id"]], "play": False})
            time.sleep(0.8)
            self.api("PUT", "/me/player/play", {"device_id": device["id"]}, body or None)
        return device

    def _friendly(self, exc: SpotifyError) -> SpotifyError:
        if exc.status == 403 and "premium" in str(exc).lower():
            return SpotifyError("O Spotify só deixa controlar a reprodução com conta Premium.", 403)
        return exc

    def _player(self, method: str, path: str, params: dict | None = None) -> None:
        try:
            self.api(method, path, params)
        except SpotifyError as exc:
            if exc.status == 404:
                raise SpotifyError("Nada tocando no Spotify agora.", 404, "NO_ACTIVE_DEVICE") from exc
            if exc.status == 403 and exc.reason in ("UNKNOWN", "") and "restrict" in str(exc).lower():
                return  # ex.: pausar o que já está pausado
            raise self._friendly(exc) from exc

    def pause(self) -> None:
        self._player("PUT", "/me/player/pause")

    def resume(self) -> None:
        state = self.playback()
        if state and state.get("device"):
            self._player("PUT", "/me/player/play", {"device_id": state["device"].get("id")})
        else:
            self.play()

    def next(self) -> None:
        self._player("POST", "/me/player/next")

    def previous(self) -> None:
        self._player("POST", "/me/player/previous")

    def set_volume(self, pct: int) -> int:
        pct = max(0, min(100, int(pct)))
        self._player("PUT", "/me/player/volume", {"volume_percent": pct})
        return pct

    def volume(self) -> int | None:
        state = self.playback()
        return (state or {}).get("device", {}).get("volume_percent")

    def shuffle(self, on: bool) -> None:
        self._player("PUT", "/me/player/shuffle", {"state": "true" if on else "false"})

    def repeat(self, mode: str) -> None:
        self._player("PUT", "/me/player/repeat", {"state": mode})

    def queue(self, uri: str) -> None:
        self._player("POST", "/me/player/queue", {"uri": uri})

    def playback(self) -> dict[str, Any] | None:
        return self.api("GET", "/me/player", {"additional_types": "track,episode"})

    # ── biblioteca e busca ──
    def search(self, query: str, kind: str, limit: int = 5) -> list[dict[str, Any]]:
        data = self.api("GET", "/search", {"q": query, "type": kind, "limit": min(limit, 10), "market": "from_token"})
        items = (data or {}).get(f"{kind}s", {}).get("items", [])
        return [i for i in items if i]

    def my_playlists(self, max_items: int = 200) -> list[dict[str, Any]]:
        items, offset = [], 0
        while offset < max_items:
            page = self.api("GET", "/me/playlists", {"limit": 50, "offset": offset}) or {}
            batch = [i for i in page.get("items", []) if i]
            items.extend(batch)
            if not page.get("next") or not batch:
                break
            offset += 50
        return items

    def liked_tracks(self, limit: int = 50) -> list[dict[str, Any]]:
        page = self.api("GET", "/me/tracks", {"limit": min(limit, 50)}) or {}
        return [i["track"] for i in page.get("items", []) if i and i.get("track")]

    def top_tracks(self, limit: int = 30) -> list[dict[str, Any]]:
        page = self.api("GET", "/me/top/tracks", {"limit": min(limit, 50), "time_range": "short_term"}) or {}
        return [t for t in page.get("items", []) if t]

    def save_track(self, track: dict[str, Any], save: bool = True) -> None:
        method = "PUT" if save else "DELETE"
        try:
            self.api(method, "/me/tracks", {"ids": track["id"]})
        except SpotifyError as exc:
            if exc.status not in (404, 410):
                raise
            self.api(method, "/me/library", {"uris": track["uri"]})  # endpoint novo da biblioteca

    def seek(self, position_ms: int) -> None:
        self._player("PUT", "/me/player/seek", {"position_ms": max(0, int(position_ms))})

    def transfer(self, device_id: str, play: bool = True) -> None:
        self.api("PUT", "/me/player", body={"device_ids": [device_id], "play": play})

    def queue_items(self) -> list[dict[str, Any]]:
        try:
            return [i for i in (self.api("GET", "/me/player/queue") or {}).get("queue", []) if i]
        except SpotifyError:
            return []

    def recently_played(self, limit: int = 10) -> list[dict[str, Any]]:
        try:
            page = self.api("GET", "/me/player/recently-played", {"limit": min(limit, 50)}) or {}
        except SpotifyError:
            return []
        seen, out = set(), []
        for i in page.get("items", []):
            track = (i or {}).get("track")
            if track and track.get("uri") not in seen:
                seen.add(track["uri"])
                out.append(track)
        return out

    def is_saved(self, track: dict[str, Any]) -> bool | None:
        try:
            data = self.api("GET", "/me/tracks/contains", {"ids": track["id"]})
        except SpotifyError as exc:
            if exc.status not in (404, 410):
                return None
            try:
                data = self.api("GET", "/me/library/contains", {"uris": track["uri"]})
            except SpotifyError:
                return None
        return bool(data[0]) if isinstance(data, list) and data else None

    def search_all(self, query: str, limit: int = 6) -> dict[str, list[dict[str, Any]]]:
        data = self.api("GET", "/search", {"q": query, "type": "track,artist,album,playlist",
                                           "limit": min(limit, 10), "market": "from_token"}) or {}
        return {kind: [i for i in (data.get(f"{kind}s") or {}).get("items", []) if i]
                for kind in ("track", "artist", "album", "playlist")}

    def token_info(self) -> dict[str, Any]:
        """Quando a conta foi autorizada e até quando vale (apps em modo dev: 180 dias)."""
        if not self._token:
            return {}
        authorized = self._token.get("authorized_at")
        return {"authorized_at": authorized,
                "expires_at": authorized + 180 * 86400 if authorized else None}

    # ── resumo para a UI ──
    def status(self) -> dict[str, Any]:
        info: dict[str, Any] = {"configured": self.configured, "connected": self.connected,
                                "device_name": self.device_name, **self.token_info()}
        if not self.connected:
            return info
        try:
            me = self.me()
            info["user"] = me.get("display_name") or me.get("id")
            info["premium"] = me.get("product") == "premium"
            info["devices"] = [{"name": d.get("name"), "active": d.get("is_active"), "volume": d.get("volume_percent")}
                               for d in self.devices()]
            info["device_online"] = any((d["name"] or "").lower() == self.device_name.lower() for d in info["devices"])
            state = self.playback()
            if state and state.get("item"):
                item = state["item"]
                info["now_playing"] = {
                    "title": item.get("name"),
                    "artist": ", ".join(a.get("name", "") for a in item.get("artists", [])) or
                              (item.get("show") or {}).get("name", ""),
                    "is_playing": state.get("is_playing"),
                    "device": (state.get("device") or {}).get("name"),
                    "image": ((item.get("album") or {}).get("images") or [{}])[-1].get("url"),
                    "shuffle": state.get("shuffle_state"),
                    "repeat": state.get("repeat_state"),
                }
        except SpotifyError as exc:
            info["error"] = str(exc)
            info["expired"] = exc.reason == "EXPIRED"
        return info

    # ── aba Música da UI ──
    def player_view(self) -> dict[str, Any]:
        view: dict[str, Any] = {"connected": self.connected, "device_name": self.device_name}
        try:
            devices = self.devices()
            view["devices"] = [{"id": d.get("id"), "name": d.get("name"), "type": d.get("type"),
                                "active": d.get("is_active"), "volume": d.get("volume_percent")} for d in devices]
            view["device_online"] = any((d.get("name") or "").lower() == self.device_name.lower() for d in devices)
            state = self.playback()
            if state and state.get("item"):
                item = state["item"]
                track = item_view(item)
                track.update({
                    "progress_ms": state.get("progress_ms") or 0,
                    "duration_ms": item.get("duration_ms") or 0,
                    "album": (item.get("album") or {}).get("name"),
                    "image_large": image_of(item.get("album") or item, large=True),
                    "liked": self.is_saved(item) if item.get("type") == "track" else None,
                })
                view["track"] = track
                view["is_playing"] = bool(state.get("is_playing"))
                view["shuffle"] = bool(state.get("shuffle_state"))
                view["repeat"] = state.get("repeat_state") or "off"
                dev = state.get("device") or {}
                view["device"] = {"id": dev.get("id"), "name": dev.get("name"), "volume": dev.get("volume_percent")}
        except SpotifyError as exc:
            view["error"] = str(exc)
            view["expired"] = exc.reason == "EXPIRED"
        return view


def image_of(obj: dict[str, Any], large: bool = False) -> str | None:
    images = [i for i in (obj or {}).get("images") or [] if i and i.get("url")]
    if not images:
        return None
    return images[0]["url"] if large else images[-1]["url"]


def item_view(item: dict[str, Any]) -> dict[str, Any]:
    """Uma música/artista/álbum/playlist resumido para a UI."""
    kind = item.get("type")
    view = {"type": kind, "uri": item.get("uri"), "id": item.get("id"), "name": item.get("name")}
    if kind == "track":
        view["subtitle"] = ", ".join(a.get("name", "") for a in item.get("artists", []))
        view["image"] = image_of(item.get("album") or {})
        view["context_uri"] = (item.get("album") or {}).get("uri")
    elif kind == "episode":
        view["subtitle"] = (item.get("show") or {}).get("name", "")
        view["image"] = image_of(item) or image_of(item.get("show") or {})
    elif kind == "album":
        view["subtitle"] = ", ".join(a.get("name", "") for a in item.get("artists", []))
        view["image"] = image_of(item)
    elif kind == "artist":
        view["subtitle"] = "Artista"
        view["image"] = image_of(item)
    elif kind == "playlist":
        owner = (item.get("owner") or {}).get("display_name") or ""
        total = (item.get("tracks") or item.get("items") or {}).get("total")
        view["subtitle"] = " · ".join(x for x in (owner, f"{total} músicas" if total is not None else "") if x)
        view["image"] = image_of(item)
    return view


client = SpotifyClient()
