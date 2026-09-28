"""Pausa a música do Spotify enquanto a Cassandra é chamada e a volta depois do pedido.

Ao ouvir o nome, se a caixa da Cassandra (librespot) estiver tocando, a música pausa — o pedido fica audível e ela
não transcreve a letra. Quando o pedido termina (ou a sessão acaba sem pedido), a música volta. Não volta se a
pessoa mexeu na música no meio ("pausa a música", "toca tal coisa", "próxima"): isso passa por play/pause/resume/
next/previous do SpotifyClient, que contam em `control_gen`.

As chamadas à Web API levam ~0,3–1 s, então tudo roda em segundo plano (a escuta não espera a rede).
"""
from __future__ import annotations

import threading

from cassandra import spotify


class MusicPause:
    def __init__(self, client: spotify.SpotifyClient | None = None) -> None:
        self._client = client or spotify.client
        self._lock = threading.Lock()  # pausar e voltar em ordem, mesmo em threads diferentes
        self._paused_device: str | None = None
        self._gen = 0

    @property
    def active(self) -> bool:
        """Há uma música pausada por nós esperando para voltar?"""
        return self._paused_device is not None

    def pause(self) -> None:
        threading.Thread(target=self._pause, name="music-pause", daemon=True).start()

    def resume(self) -> None:
        if self.active:
            threading.Thread(target=self._resume, name="music-resume", daemon=True).start()

    def _pause(self) -> None:
        c = self._client
        if not (c.configured and c.connected):
            return
        with self._lock:
            if self._paused_device:
                return  # já pausada por um chamado anterior
            try:
                state = c.playback() or {}
                device = state.get("device") or {}
                if not state.get("is_playing") or (device.get("name") or "").lower() != c.device_name.lower():
                    return  # nada tocando, ou tocando em outro aparelho (celular, PC): não é nosso
                c._player("PUT", "/me/player/pause")
                self._paused_device = device.get("id") or ""
                self._gen = c.control_gen
                print("[MUSICA] Pausada para ouvir o pedido.", flush=True)
            except Exception as exc:  # noqa: BLE001 — a música nunca pode atrapalhar a escuta
                print(f"[MUSICA] Não pausou: {exc}", flush=True)

    def _resume(self) -> None:
        c = self._client
        with self._lock:
            device, self._paused_device = self._paused_device, None
            if device is None:
                return
            if c.control_gen != self._gen:
                print("[MUSICA] Não volta: o pedido mexeu na música.", flush=True)
                return
            try:
                c._player("PUT", "/me/player/play", {"device_id": device} if device else None)
                print("[MUSICA] Voltou a tocar.", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[MUSICA] Não voltou: {exc}", flush=True)
