"""O que o microfone está fazendo, ao vivo, para a aba "Microfone" da UI: se há microfone conectado, qual, a
taxa em que abriu, o nível de som agora, em que etapa a Cassandra está (esperando o nome / ouvindo o pedido /
pensando) e um log do que foi captado (fala detectada, nome ou não, texto transcrito, pedido, resposta, erros).

Fica só na memória (as últimas 400 entradas) — nada vai para o disco.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

MAX_EVENTS = 400


class MicMonitor:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)
        self._next_id = 1
        self.present: bool | None = None  # None = ainda não checou (ou modo sem microfone)
        self.device = ""
        self.rate = 0
        self.phase = "iniciando"
        self.threshold = 0
        self._level = 0.0
        self._level_at = 0.0
        self._peak = 0.0

    def event(self, kind: str, text: str) -> None:
        """kind: status | heard | no_wake | wake | transcribed | ignored | command | response | error."""
        with self._lock:
            self._events.append({"id": self._next_id, "ts": time.time(), "kind": kind, "text": text})
            self._next_id += 1

    def set(self, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self, key, value)

    def level(self, rms: float) -> None:
        """Chamado a cada quadro de 30 ms: guarda o nível atual e um pico que decai devagar."""
        now = time.monotonic()
        self._level = rms
        self._level_at = now
        self._peak = max(rms, self._peak * 0.97)

    def snapshot(self, after: int = 0) -> dict[str, Any]:
        with self._lock:
            events = [e for e in self._events if e["id"] > after]
        live = time.monotonic() - self._level_at < 1.5  # o microfone está sendo lido agora
        return {
            "present": self.present,
            "device": self.device,
            "rate": self.rate,
            "phase": self.phase,
            "listening": live,
            "level": round(self._level if live else 0.0),
            "peak": round(self._peak if live else 0.0),
            "threshold": self.threshold,
            "events": events,
        }


monitor = MicMonitor()
