"""Gerenciador de rotinas: executa sequências de ações ao disparar alarmes ou horários."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

# Labels exibidos no dashboard
ACTION_LABELS: dict[str, str] = {
    "noticias": "Notícias do dia",
    "cotacao": "Cotações do mercado",
    "clima": "Previsão do tempo",
    "esporte": "Resultados esportivos",
    "transito": "Trânsito em tempo real",
    "falar": "Falar mensagem personalizada",
}

# Query padrão por categoria (usada ao executar a ação)
_CATEGORY_QUERIES: dict[str, str] = {
    "noticias": "principais notícias e manchetes do dia de hoje {date}",
    "cotacao": "cotações do mercado financeiro hoje {date}: dólar, euro, ibovespa, bitcoin",
    "clima": "previsão do tempo para hoje {date} nas principais cidades brasileiras",
    "esporte": "resultados esportivos de hoje {date}: futebol, fórmula 1 e outros",
    "transito": "condições de trânsito em tempo real nas principais vias e cidades hoje {date}",
}


@dataclass
class RoutineAction:
    type: str   # noticias | cotacao | clima | esporte | transito | falar
    text: str = ""  # somente para type="falar"


@dataclass
class RoutineTrigger:
    type: str        # "alarm" | "time"
    alarm_id: str = ""      # para type="alarm"
    time_hhmm: str = ""     # para type="time"


@dataclass
class Routine:
    id: str
    name: str
    trigger: RoutineTrigger
    actions: list[RoutineAction]
    enabled: bool = True
    created_at: str = ""


class RoutineManager:
    def __init__(self, voice_output, llm, db_path: str = "data/routines.json") -> None:
        self._voice = voice_output
        self._llm = llm
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._routines: list[Routine] = self._load()
        self._fired_times: dict[str, str] = {}   # routine_id → "YYYY-MM-DD HH:MM"
        self._running = True
        threading.Thread(target=self._time_monitor, daemon=True).start()

    # ── Public API ────────────────────────────────────────────────────────────

    def add_routine(self, name: str, trigger: dict, actions: list[dict]) -> Routine:
        trig = RoutineTrigger(
            type=trigger.get("type", "time"),
            alarm_id=trigger.get("alarm_id", ""),
            time_hhmm=trigger.get("time_hhmm", ""),
        )
        acts = [RoutineAction(type=a.get("type", "falar"), text=a.get("text", ""))
                for a in actions if a.get("type")]
        routine = Routine(
            id=uuid4().hex[:10],
            name=(name or "Rotina").strip(),
            trigger=trig,
            actions=acts,
            enabled=True,
            created_at=datetime.now().isoformat(),
        )
        with self._lock:
            self._routines.append(routine)
            self._save_locked()
        return routine

    def remove_routine(self, routine_id: str) -> bool:
        with self._lock:
            before = len(self._routines)
            self._routines = [r for r in self._routines if r.id != routine_id]
            changed = len(self._routines) != before
            if changed:
                self._save_locked()
            return changed

    def toggle_routine(self, routine_id: str, enabled: bool) -> bool:
        with self._lock:
            for r in self._routines:
                if r.id == routine_id:
                    r.enabled = enabled
                    self._save_locked()
                    return True
            return False

    def list_routines(self) -> list[dict]:
        with self._lock:
            return [_to_dict(r) for r in self._routines]

    def run_routine(self, routine_id: str) -> bool:
        """Dispara manualmente uma rotina (ex: botão no dashboard)."""
        with self._lock:
            routine = next((r for r in self._routines if r.id == routine_id), None)
        if routine is None:
            return False
        threading.Thread(target=self._execute, args=(routine,), daemon=True).start()
        return True

    def on_alarm_fire(self, alarm_id: str) -> None:
        """Chamado pelo AlarmManager quando um alarme toca."""
        with self._lock:
            routines = [r for r in self._routines
                        if r.enabled and r.trigger.type == "alarm"
                        and r.trigger.alarm_id == alarm_id]
        for r in routines:
            threading.Thread(target=self._execute, args=(r,), daemon=True).start()

    # ── Execução ──────────────────────────────────────────────────────────────

    def _execute(self, routine: Routine) -> None:
        # Imports locais para evitar ciclo de importação
        from skills.web_search.skill import _client as web_client, _FORMAT_PROMPTS

        today = datetime.now().strftime("%d/%m/%Y")
        for action in routine.actions:
            try:
                if action.type == "falar":
                    if action.text:
                        self._voice.speak(action.text)
                    continue

                query = _CATEGORY_QUERIES.get(action.type, "").format(date=today)
                if not query:
                    continue

                raw = web_client.query(query)
                if not raw:
                    continue

                fmt = _FORMAT_PROMPTS.get(action.type, _FORMAT_PROMPTS.get("web_geral", ""))
                response = self._llm.answer(
                    user_text=f"Resultado da busca:\n{raw}",
                    system_prompt=fmt,
                    history=[],
                )
                self._voice.speak(response)
            except Exception as exc:
                print(f"[ROUTINE] Erro na ação '{action.type}': {exc}")

    # ── Monitor de horários ───────────────────────────────────────────────────

    def _time_monitor(self) -> None:
        while self._running:
            now = datetime.now()
            current_hhmm = now.strftime("%H:%M")
            date_min = now.strftime("%Y-%m-%d %H:%M")
            with self._lock:
                to_fire = []
                for r in self._routines:
                    if not r.enabled or r.trigger.type != "time":
                        continue
                    if r.trigger.time_hhmm != current_hhmm:
                        continue
                    if self._fired_times.get(r.id) == date_min:
                        continue
                    self._fired_times[r.id] = date_min
                    to_fire.append(r)
            for r in to_fire:
                threading.Thread(target=self._execute, args=(r,), daemon=True).start()
            time.sleep(30)

    # ── Persistência ─────────────────────────────────────────────────────────

    def _save_locked(self) -> None:
        payload = [_to_dict(r) for r in self._routines]
        self._db_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _load(self) -> list[Routine]:
        if not self._db_path.exists():
            return []
        try:
            raw = json.loads(self._db_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        routines: list[Routine] = []
        for row in raw if isinstance(raw, list) else []:
            try:
                td = row.get("trigger", {})
                trig = RoutineTrigger(
                    type=td.get("type", "time"),
                    alarm_id=td.get("alarm_id", ""),
                    time_hhmm=td.get("time_hhmm", ""),
                )
                acts = [RoutineAction(type=a.get("type", "falar"), text=a.get("text", ""))
                        for a in row.get("actions", [])]
                routines.append(Routine(
                    id=str(row["id"]),
                    name=str(row.get("name", "Rotina")),
                    trigger=trig,
                    actions=acts,
                    enabled=bool(row.get("enabled", True)),
                    created_at=str(row.get("created_at", "")),
                ))
            except Exception:
                continue
        return routines


def _to_dict(r: Routine) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "trigger": {
            "type": r.trigger.type,
            "alarm_id": r.trigger.alarm_id,
            "time_hhmm": r.trigger.time_hhmm,
        },
        "actions": [{"type": a.type, "text": a.text} for a in r.actions],
        "enabled": r.enabled,
        "created_at": r.created_at,
    }
