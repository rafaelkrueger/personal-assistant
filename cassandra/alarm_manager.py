"""Persistent alarm manager with repeating ring playback."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from cassandra.sounds import SoundPlayer


@dataclass
class Alarm:
    id: str
    label: str
    time_hhmm: str
    recurring_daily: bool
    next_trigger_at: str
    enabled: bool = True


class AlarmManager:
    def __init__(
        self,
        ring_sound_path: str,
        sound_player: SoundPlayer,
        db_path: str = "data/alarms.json",
    ) -> None:
        self.ring_sound_path = ring_sound_path
        self.sound_player = sound_player
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._alarms: list[Alarm] = self._load()
        self._ringing_alarm_ids: set[str] = set()
        self._running = True
        self._monitor = threading.Thread(target=self._run_monitor, daemon=True)
        self._ringer = threading.Thread(target=self._run_ringer, daemon=True)
        self._monitor.start()
        self._ringer.start()

    def add_alarm(self, time_hhmm: str, recurring_daily: bool, label: str = "Alarme") -> Alarm:
        normalized = self._normalize_time(time_hhmm)
        next_trigger = self._compute_next_trigger(normalized)
        alarm = Alarm(
            id=uuid4().hex[:10],
            label=label.strip() or "Alarme",
            time_hhmm=normalized,
            recurring_daily=recurring_daily,
            next_trigger_at=next_trigger.isoformat(),
            enabled=True,
        )
        with self._lock:
            self._alarms.append(alarm)
            self._save_locked()
        return alarm

    def remove_alarm(self, alarm_id: str) -> bool:
        with self._lock:
            before = len(self._alarms)
            self._alarms = [a for a in self._alarms if a.id != alarm_id]
            self._ringing_alarm_ids.discard(alarm_id)
            changed = len(self._alarms) != before
            if changed:
                self._save_locked()
            return changed

    def stop_ringing(self) -> bool:
        with self._lock:
            if not self._ringing_alarm_ids:
                return False
            self._ringing_alarm_ids.clear()
            return True

    def list_alarms(self) -> list[dict]:
        with self._lock:
            return [asdict(a) for a in self._alarms]

    def is_ringing(self) -> bool:
        with self._lock:
            return bool(self._ringing_alarm_ids)

    def _run_monitor(self) -> None:
        while self._running:
            now = datetime.now()
            dirty = False
            with self._lock:
                for alarm in self._alarms:
                    if not alarm.enabled:
                        continue
                    trigger = self._parse_dt(alarm.next_trigger_at)
                    if trigger <= now:
                        self._ringing_alarm_ids.add(alarm.id)
                        if alarm.recurring_daily:
                            next_dt = self._compute_next_trigger(alarm.time_hhmm)
                            if next_dt <= now:
                                next_dt = next_dt + timedelta(days=1)
                            alarm.next_trigger_at = next_dt.isoformat()
                        else:
                            alarm.enabled = False
                        dirty = True
                if dirty:
                    self._save_locked()
            time.sleep(1.0)

    def _run_ringer(self) -> None:
        while self._running:
            if self.is_ringing():
                self.sound_player.play(self.ring_sound_path)
                time.sleep(2.5)
            else:
                time.sleep(0.4)

    def _load(self) -> list[Alarm]:
        if not self.db_path.exists():
            return []
        try:
            raw = json.loads(self.db_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(raw, list):
            return []
        alarms: list[Alarm] = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            try:
                alarm = Alarm(
                    id=str(row["id"]),
                    label=str(row.get("label", "Alarme")),
                    time_hhmm=self._normalize_time(str(row["time_hhmm"])),
                    recurring_daily=bool(row.get("recurring_daily", False)),
                    next_trigger_at=str(row["next_trigger_at"]),
                    enabled=bool(row.get("enabled", True)),
                )
            except Exception:
                continue
            alarms.append(alarm)
        return alarms

    def _save_locked(self) -> None:
        payload = [asdict(a) for a in self._alarms]
        self.db_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _normalize_time(value: str) -> str:
        raw = value.strip()
        if ":" in raw:
            hh, mm = raw.split(":", 1)
        else:
            hh, mm = raw, "00"
        hour = int(hh)
        minute = int(mm)
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError("Horario invalido. Use formato HH:MM.")
        return f"{hour:02d}:{minute:02d}"

    @staticmethod
    def _compute_next_trigger(time_hhmm: str) -> datetime:
        hour, minute = [int(p) for p in time_hhmm.split(":")]
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target

    @staticmethod
    def _parse_dt(value: str) -> datetime:
        return datetime.fromisoformat(value)
