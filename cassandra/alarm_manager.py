"""Persistent alarm manager with ring playback (a few rings, then it stops by itself) and calendar dates."""
from __future__ import annotations

import calendar
import json
import os
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
    days_of_week: list[int] | None  # 0=Mon..6=Sun; None = every day (if recurring)
    next_trigger_at: str
    enabled: bool = True
    date_ymd: str | None = None  # YYYY-MM-DD — one-shot on this exact date
    day_of_month: int | None = None  # 1-31 — monthly


# Quantas vezes o alarme toca antes de parar sozinho (ALARM_RING_TIMES; 0 = toca até alguém parar).
RING_TIMES = max(0, int(os.getenv("ALARM_RING_TIMES", "5") or 5))
RING_GAP_SECONDS = 0.4  # pausa entre um toque e o próximo


class AlarmManager:
    def __init__(
        self,
        ring_sound_path: str,
        sound_player: SoundPlayer,
        db_path: str = "data/alarms.json",
        on_alarm_fire=None,
    ) -> None:
        self.ring_sound_path = ring_sound_path
        self.sound_player = sound_player
        self._on_alarm_fire = on_alarm_fire
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._alarms: list[Alarm] = self._load()
        self._ringing_alarm_ids: set[str] = set()
        self._rings_done = 0  # toques já dados desde que o alarme começou (zera a cada alarme novo)
        self._running = True
        self._monitor = threading.Thread(target=self._run_monitor, daemon=True)
        self._ringer = threading.Thread(target=self._run_ringer, daemon=True)
        self._monitor.start()
        self._ringer.start()

    def add_alarm(
        self,
        time_hhmm: str,
        recurring_daily: bool,
        label: str = "Alarme",
        days_of_week: list[int] | None = None,
        date_ymd: str | None = None,
        day_of_month: int | None = None,
    ) -> Alarm:
        normalized = self._normalize_time(time_hhmm)
        date_ymd = self._normalize_date(date_ymd)
        day_of_month = self._normalize_day_of_month(day_of_month)
        dow = sorted(set(days_of_week)) if days_of_week else None
        if date_ymd:
            recurring_daily = False
            dow = None
            day_of_month = None
        elif day_of_month:
            recurring_daily = False
            dow = None
        next_trigger = self._compute_next_trigger(
            normalized, dow, date_ymd=date_ymd, day_of_month=day_of_month
        )
        alarm = Alarm(
            id=uuid4().hex[:10],
            label=label.strip() or "Alarme",
            time_hhmm=normalized,
            recurring_daily=recurring_daily,
            days_of_week=dow,
            next_trigger_at=next_trigger.isoformat(),
            enabled=True,
            date_ymd=date_ymd,
            day_of_month=day_of_month,
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

    def ringing(self) -> list[dict]:
        """Alarmes tocando agora (id, label, time_hhmm) — a UI mostra o aviso para parar."""
        with self._lock:
            return [{"id": a.id, "label": a.label, "time_hhmm": a.time_hhmm}
                    for a in self._alarms if a.id in self._ringing_alarm_ids]

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
                        just_fired = alarm.id not in self._ringing_alarm_ids
                        self._ringing_alarm_ids.add(alarm.id)
                        if just_fired:
                            self._rings_done = 0  # outro alarme disparou: toca as vezes dele
                        if just_fired and self._on_alarm_fire:
                            fired_id = alarm.id
                            threading.Thread(
                                target=self._on_alarm_fire, args=(fired_id,), daemon=True
                            ).start()
                        if self._is_recurring(alarm):
                            next_dt = self._compute_next_trigger(
                                alarm.time_hhmm,
                                alarm.days_of_week,
                                date_ymd=None,
                                day_of_month=alarm.day_of_month,
                                after=now,
                            )
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
                # Um toque de cada vez (sem sobrepor) e, ao parar o alarme, o som corta na hora.
                proc = self.sound_player.play(self.ring_sound_path)
                while proc is not None and proc.poll() is None and self.is_ringing():
                    time.sleep(0.2)
                if proc is not None and proc.poll() is None:
                    proc.terminate()
                if not self._count_ring():
                    continue  # já tocou as vezes combinadas (ou foi parado): fica em silêncio
                # Sem som para tocar (arquivo/saída indisponível), espera o tempo de um toque.
                time.sleep(2.5 if proc is None else RING_GAP_SECONDS)
            else:
                time.sleep(0.4)

    def _count_ring(self) -> bool:
        """Conta um toque dado. Ao chegar em RING_TIMES o alarme para sozinho. -> ainda está tocando?"""
        with self._lock:
            if not self._ringing_alarm_ids:
                return False
            self._rings_done += 1
            if RING_TIMES and self._rings_done >= RING_TIMES:
                self._ringing_alarm_ids.clear()
                return False
            return True

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
                raw_days = row.get("days_of_week")
                dow = [int(d) for d in raw_days] if isinstance(raw_days, list) else None
                raw_dom = row.get("day_of_month")
                date_ymd = self._normalize_date(row.get("date_ymd"))
                day_of_month = self._normalize_day_of_month(raw_dom) if raw_dom not in (None, "") else None
                alarm = Alarm(
                    id=str(row["id"]),
                    label=str(row.get("label", "Alarme")),
                    time_hhmm=self._normalize_time(str(row["time_hhmm"])),
                    recurring_daily=bool(row.get("recurring_daily", False)),
                    days_of_week=dow,
                    next_trigger_at=str(row["next_trigger_at"]),
                    enabled=bool(row.get("enabled", True)),
                    date_ymd=date_ymd,
                    day_of_month=day_of_month,
                )
            except Exception:
                continue
            alarms.append(alarm)
        return alarms

    def _save_locked(self) -> None:
        payload = [asdict(a) for a in self._alarms]
        self.db_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _is_recurring(alarm: Alarm) -> bool:
        return bool(alarm.recurring_daily or alarm.days_of_week is not None or alarm.day_of_month)

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
    def _normalize_date(value: str | None) -> str | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.strptime(raw, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("Data inválida. Use formato AAAA-MM-DD.") from exc
        return parsed.strftime("%Y-%m-%d")

    @staticmethod
    def _normalize_day_of_month(value: int | str | None) -> int | None:
        if value in (None, ""):
            return None
        day = int(value)
        if day < 1 or day > 31:
            raise ValueError("Dia do mês inválido. Use um número de 1 a 31.")
        return day

    @staticmethod
    def _compute_next_trigger(
        time_hhmm: str,
        days_of_week: list[int] | None = None,
        date_ymd: str | None = None,
        day_of_month: int | None = None,
        after: datetime | None = None,
    ) -> datetime:
        hour, minute = [int(p) for p in time_hhmm.split(":")]
        now = after if after is not None else datetime.now()
        if date_ymd:
            year, month, day = [int(p) for p in date_ymd.split("-")]
            return datetime(year, month, day, hour, minute, 0, 0)
        if day_of_month:
            year, month = now.year, now.month
            for _ in range(14):
                last = calendar.monthrange(year, month)[1]
                day = min(int(day_of_month), last)
                candidate = datetime(year, month, day, hour, minute, 0, 0)
                if candidate > now:
                    return candidate
                month += 1
                if month > 12:
                    month = 1
                    year += 1
            raise ValueError("Não achei o próximo dia do mês.")
        base = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        for offset in range(8):
            candidate = base + timedelta(days=offset)
            if candidate <= now:
                continue
            if not days_of_week or candidate.weekday() in days_of_week:
                return candidate
        candidate = base + timedelta(days=1)
        while days_of_week and candidate.weekday() not in days_of_week:
            candidate += timedelta(days=1)
        return candidate

    @staticmethod
    def _parse_dt(value: str) -> datetime:
        return datetime.fromisoformat(value)
