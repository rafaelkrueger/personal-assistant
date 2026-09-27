"""Background timer management for the assistant."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

# Um timer que acabou de tocar continua na lista (como "tocando") por este tempo, para a UI mostrar.
_SHOW_FIRED_SECONDS = 10.0


@dataclass
class FiredTimer:
    name: str
    duration_seconds: int


def format_duration(seconds: int) -> str:
    """Human-readable Portuguese duration string."""
    if seconds < 60:
        unit = "segundo" if seconds == 1 else "segundos"
        return f"{seconds} {unit}"
    if seconds < 3600:
        mins = seconds // 60
        secs = seconds % 60
        unit = "minuto" if mins == 1 else "minutos"
        label = f"{mins} {unit}"
        if secs:
            su = "segundo" if secs == 1 else "segundos"
            label += f" e {secs} {su}"
        return label
    hours = seconds // 3600
    mins = (seconds % 3600) // 60
    unit = "hora" if hours == 1 else "horas"
    label = f"{hours} {unit}"
    if mins:
        mu = "minuto" if mins == 1 else "minutos"
        label += f" e {mins} {mu}"
    return label


class TimerManager:
    """Manages named countdown timers in daemon background threads.

    When a timer fires it:
      1. Appends to the internal fired queue.
      2. Sets `on_fire` (a threading.Event) so the VAD recorder can
         abort its current listening window immediately.
    """

    def __init__(self, on_fire: threading.Event) -> None:
        self._lock = threading.Lock()
        self._active: dict[str, threading.Timer] = {}
        self._fired: list[FiredTimer] = []
        self._ends: dict[str, tuple[int, float]] = {}  # nome -> (duração, fim em time.time())
        self._recent: dict[str, tuple[int, float]] = {}  # tocaram há pouco: nome -> (duração, quando)
        self.on_fire = on_fire

    def add(self, name: str, duration_seconds: int) -> None:
        with self._lock:
            existing = self._active.pop(name, None)
        if existing:
            existing.cancel()
        t = threading.Timer(duration_seconds, self._fire, args=(name, duration_seconds))
        t.daemon = True
        with self._lock:
            self._active[name] = t
            self._ends[name] = (duration_seconds, time.time() + duration_seconds)
            self._recent.pop(name, None)
        t.start()

    def _fire(self, name: str, duration_seconds: int) -> None:
        with self._lock:
            self._active.pop(name, None)
            self._ends.pop(name, None)
            self._recent[name] = (duration_seconds, time.time())
            self._fired.append(FiredTimer(name=name, duration_seconds=duration_seconds))
        self.on_fire.set()

    def pop_fired(self) -> list[FiredTimer]:
        with self._lock:
            fired, self._fired = list(self._fired), []
        return fired

    def has_fired(self) -> bool:
        with self._lock:
            return bool(self._fired)

    def cancel(self, name: str) -> bool:
        with self._lock:
            t = self._active.pop(name, None)
            self._ends.pop(name, None)
            self._recent.pop(name, None)
        if t:
            t.cancel()
            return True
        return False

    def active_names(self) -> list[str]:
        with self._lock:
            return list(self._active.keys())

    def snapshot(self) -> list[dict]:
        """Timers ativos (quanto falta) e os que tocaram nos últimos segundos — para a UI."""
        now = time.time()
        with self._lock:
            self._recent = {n: v for n, v in self._recent.items() if now - v[1] < _SHOW_FIRED_SECONDS}
            items = [{"name": n, "label": format_duration(d), "duration": d, "ends_at": end,
                      "remaining": max(0.0, round(end - now, 1)), "fired": False}
                     for n, (d, end) in self._ends.items()]
            items += [{"name": n, "label": format_duration(d), "duration": d, "ends_at": at,
                       "remaining": 0.0, "fired": True} for n, (d, at) in self._recent.items()]
        return sorted(items, key=lambda i: i["ends_at"])
