"""Hábitos: o que a pessoa quer fazer todo dia (ou toda semana) e o registro do que ela fez.

Tudo fica em data/habits.json (fora do git): a lista de hábitos e, para cada um, quanto foi feito em cada dia. A aba
Hábitos da UI lê overview(), que já traz as contas prontas: a grade do ano, a consistência, as sequências e as
séries dos gráficos.

Um hábito tem uma meta por DIA ("8 copos por dia", ou simplesmente "fazer", que é meta 1) ou por SEMANA ("200
páginas por semana", "3 vezes por semana"). O de dia pode valer só em alguns dias da semana (ex.: academia seg/qua/
sex): os outros dias não contam nem a favor nem contra.

- Dia cumprido: o que foi feito no dia >= a meta. Semana cumprida (segunda a domingo): a soma da semana >= a meta.
- Consistência: dias (ou semanas) cumpridos ÷ dias (ou semanas) que já passaram desde que o hábito começou — o
  começo é a criação dele ou o primeiro registro, o que vier antes. A semana em curso só entra se já foi cumprida.
- Sequência: dias (ou semanas) cumpridos seguidos até hoje; o dia de hoje ainda em aberto não quebra a sequência.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

PATH = Path("data/habits.json")
_lock = threading.Lock()

# Cores oferecidas ao criar um hábito (claras o bastante para a grade no fundo escuro). A primeira livre é o padrão.
COLORS = ["#8ec5ff", "#f6d07a", "#f4a3b4", "#86d6c4", "#b5a8f0", "#f2a97c", "#a3d977", "#e79be0"]
PERIODS = ("day", "week")
ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]  # segunda = 0 … domingo = 6 (date.weekday())
WEEKS_IN_CHART = 12


def _today() -> date:
    return date.today()


def _load() -> dict[str, Any]:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data["habits"] = [h for h in data.get("habits") or [] if isinstance(h, dict) and h.get("id")]
    data["log"] = data.get("log") if isinstance(data.get("log"), dict) else {}
    return data


def _save(data: dict[str, Any]) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_name(f"{PATH.name}.tmp{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, PATH)


def _number(raw: Any, default: float = 0.0) -> float:
    try:
        return float(str(raw).replace(",", "."))
    except (TypeError, ValueError):
        return default


def _clean(raw: dict[str, Any], current: dict[str, Any] | None, used_colors: list[str]) -> dict[str, Any]:
    """Os campos de um hábito, validados. Na edição, o que não veio fica como estava. ValueError sem nome."""
    base = dict(current or {})
    name = str(raw.get("name", base.get("name", ""))).strip()[:60]
    if not name:
        raise ValueError("Dê um nome ao hábito (ex.: Beber água).")
    period = raw.get("period", base.get("period", "day"))
    period = period if period in PERIODS else "day"
    target = _number(raw.get("target", base.get("target", 1)), 1.0)
    target = min(100000.0, target) if target > 0 else 1.0
    days = raw.get("weekdays", base.get("weekdays", ALL_DAYS))
    days = sorted({int(d) for d in days if str(d).lstrip("-").isdigit() and 0 <= int(d) <= 6}) if isinstance(days, list) else []
    color = str(raw.get("color", base.get("color", ""))).strip()
    if not (len(color) == 7 and color.startswith("#")):
        color = next((c for c in COLORS if c not in used_colors), COLORS[len(used_colors) % len(COLORS)])
    return {
        "name": name, "emoji": str(raw.get("emoji", base.get("emoji", ""))).strip()[:8], "color": color,
        "period": period, "target": int(target) if target == int(target) else round(target, 2),
        "unit": str(raw.get("unit", base.get("unit", ""))).strip()[:20],
        "weekdays": (days or ALL_DAYS) if period == "day" else ALL_DAYS,
    }


def save(raw: dict[str, Any]) -> dict[str, Any]:
    """Cria um hábito — ou, com `id`, edita. KeyError se o id não existe; ValueError se faltar o nome."""
    with _lock:
        data = _load()
        habit_id = str(raw.get("id") or "").strip()
        current = next((h for h in data["habits"] if h["id"] == habit_id), None) if habit_id else None
        if habit_id and current is None:
            raise KeyError(habit_id)
        fields = _clean(raw, current, [h.get("color") for h in data["habits"] if h is not current])
        if current is None:
            current = {"id": uuid.uuid4().hex[:10], "created": _today().isoformat()}
            data["habits"].append(current)
        current.update(fields)
        _save(data)
        return dict(current)


def remove(habit_id: str) -> bool:
    """Apaga o hábito e todo o registro dele."""
    with _lock:
        data = _load()
        keep = [h for h in data["habits"] if h["id"] != habit_id]
        if len(keep) == len(data["habits"]):
            return False
        data["habits"] = keep
        data["log"].pop(habit_id, None)
        _save(data)
    return True


def log(habit_id: str, day: str | None = None, amount: Any = None, delta: Any = None, toggle: bool = False) -> float:
    """Registra o que foi feito num dia (padrão: hoje). `amount` define o valor do dia, `delta` soma (ou tira) e
    `toggle` alterna entre nada e a meta cumprida. Devolve o valor do dia. KeyError se o hábito não existe;
    ValueError para data inválida ou no futuro."""
    try:
        when = date.fromisoformat(str(day)[:10]) if day else _today()
    except ValueError as exc:
        raise ValueError("Data inválida (use AAAA-MM-DD).") from exc
    if when > _today():
        raise ValueError("Não dá para registrar um dia que ainda não chegou.")
    with _lock:
        data = _load()
        habit = next((h for h in data["habits"] if h["id"] == habit_id), None)
        if habit is None:
            raise KeyError(habit_id)
        entries = data["log"].setdefault(habit_id, {})
        now = float(entries.get(when.isoformat(), 0))
        # Marcar um dia "feito": a meta do dia; num hábito semanal, uma unidade (1 vez, ou o que a pessoa ajustar).
        full = float(habit["target"]) if habit.get("period") != "week" else 1.0
        if toggle:
            value = 0.0 if now > 0 else full
        elif delta is not None:
            value = now + _number(delta)
        else:
            value = _number(amount)
        value = round(max(0.0, min(1_000_000.0, value)), 2)
        if value > 0:
            entries[when.isoformat()] = int(value) if value == int(value) else value
        else:
            entries.pop(when.isoformat(), None)
        _save(data)
    return value


# ── contas ────────────────────────────────────────────────────────────────────

def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _start(habit: dict[str, Any], entries: dict[str, float], today: date) -> date:
    """Quando o hábito começou a valer: a criação ou o primeiro registro (quem preenche dias antigos não é punido)."""
    try:
        created = date.fromisoformat(str(habit.get("created") or "")[:10])
    except ValueError:
        created = today
    first = min(entries) if entries else None
    return min(created, date.fromisoformat(first)) if first else min(created, today)


def _pct(done: int, total: int) -> int | None:
    return round(done / total * 100) if total else None


def _units(habit: dict[str, Any], entries: dict[str, float], first: date, last: date) -> list[tuple[date, bool, float]]:
    """A linha do tempo do hábito entre duas datas, na unidade dele: (início, cumpriu?, quanto da meta) por dia
    previsto (hábito de dia) ou por semana (hábito de semana)."""
    target = float(habit["target"])
    out: list[tuple[date, bool, float]] = []
    if habit.get("period") == "week":
        week = _monday(first)
        while week <= last:
            total = sum(float(entries.get((week + timedelta(days=i)).isoformat(), 0)) for i in range(7))
            out.append((week, total >= target, min(1.0, total / target)))
            week += timedelta(days=7)
        return out
    days = set(habit.get("weekdays") or ALL_DAYS)
    d = first
    while d <= last:
        if d.weekday() in days:
            amount = float(entries.get(d.isoformat(), 0))
            out.append((d, amount >= target, min(1.0, amount / target)))
        d += timedelta(days=1)
    return out


def _streaks(units: list[tuple[date, bool, float]], open_last: bool) -> tuple[int, int]:
    """(sequência atual, melhor sequência). `open_last`: a última unidade (hoje / esta semana) ainda está em curso —
    se não foi cumprida, não quebra a sequência atual."""
    best = run = 0
    for _when, done, _ratio in units:
        run = run + 1 if done else 0
        best = max(best, run)
    tail = units[:-1] if units and open_last and not units[-1][1] else units
    current = 0
    for _when, done, _ratio in reversed(tail):
        if not done:
            break
        current += 1
    return current, best


def _describe(habit: dict[str, Any], entries: dict[str, float], year: int, today: date) -> dict[str, Any]:
    weekly = habit.get("period") == "week"
    target = float(habit["target"])
    start = _start(habit, entries, today)
    units = _units(habit, entries, start, today)
    current, best = _streaks(units, open_last=True)
    # Consistência: a unidade em curso (hoje / esta semana) só conta se já foi cumprida.
    closed = units[:-1] if units and not units[-1][1] and (weekly or units[-1][0] == today) else units
    in_year = [u for u in closed if u[0].year == year or (weekly and (u[0] + timedelta(days=6)).year == year)]
    recent_from = today - timedelta(days=29)
    recent = [u for u in closed if u[0] >= (_monday(recent_from) if weekly else recent_from)]
    # A grade do ano: quanto de cada dia foi preenchido (0–1). No hábito semanal, um dia "cheio" é um sétimo da meta.
    day_goal = target / 7 if weekly else target
    cells = {d: round(min(1.0, float(a) / day_goal), 2) for d, a in entries.items() if d[:4] == str(year) and float(a) > 0}
    week_total = sum(float(entries.get((_monday(today) + timedelta(days=i)).isoformat(), 0)) for i in range(7))
    amount_today = float(entries.get(today.isoformat(), 0))
    return {
        **habit, "start": start.isoformat(),
        "cells": cells, "amounts": {d: a for d, a in entries.items() if d[:4] == str(year)},
        "pct": _pct(sum(1 for u in in_year if u[1]), len(in_year)),
        "recent_pct": _pct(sum(1 for u in recent if u[1]), len(recent)),
        "done_count": sum(1 for u in in_year if u[1]), "total_count": len(in_year),
        "streak": current, "best_streak": best,
        "today": {
            "amount": amount_today,
            "scheduled": weekly or today.weekday() in (habit.get("weekdays") or ALL_DAYS),
            "progress": week_total if weekly else amount_today,  # o que conta para a meta em curso
            "done": (week_total if weekly else amount_today) >= target,
        },
    }


def _ratio(units: list[tuple[date, bool, float]]) -> float | None:
    return sum(1.0 if u[1] else 0.0 for u in units) / len(units) if units else None


def overview(year: int | None = None) -> dict[str, Any]:
    """Tudo o que a aba Hábitos mostra, com as contas prontas."""
    today = _today()
    year = year if year and 2000 <= year <= today.year else today.year
    with _lock:
        data = _load()
    habits = [_describe(h, data["log"].get(h["id"], {}), year, today) for h in data["habits"]]

    # Consistência por semana (as últimas 12): em cada semana, a média do quanto cada hábito cumpriu.
    weeks = []
    for back in range(WEEKS_IN_CHART - 1, -1, -1):
        start = _monday(today) - timedelta(days=7 * back)
        end = min(start + timedelta(days=6), today)
        parts = []
        for h in data["habits"]:
            entries = data["log"].get(h["id"], {})
            if _start(h, entries, today) > end:
                continue  # o hábito ainda não existia nessa semana
            units = _units(h, entries, max(start, _start(h, entries, today)), end)
            if h.get("period") == "week":
                parts.append(units[0][2] if units else 0.0)
            elif units:
                parts.append(sum(1.0 if u[1] else 0.0 for u in units) / len(units))
        weeks.append({"start": start.isoformat(), "pct": round(sum(parts) / len(parts) * 100) if parts else None})

    # Por dia da semana e por mês: só os hábitos de dia (num hábito semanal o dia não tem "cumpriu ou não").
    by_weekday: list[list[int]] = [[0, 0] for _ in range(7)]
    by_month: list[list[int]] = [[0, 0] for _ in range(12)]
    for h in data["habits"]:
        entries = data["log"].get(h["id"], {})
        first = max(_start(h, entries, today), date(year, 1, 1))
        last = min(today, date(year, 12, 31))
        if h.get("period") == "week":
            for when, done, _ratio_ in _units(h, entries, first, last):
                if when + timedelta(days=6) <= today or done:
                    by_month[min(when + timedelta(days=3), last).month - 1][0] += int(done)
                    by_month[min(when + timedelta(days=3), last).month - 1][1] += 1
            continue
        for when, done, _ratio_ in _units(h, entries, first, last):
            if when == today and not done:
                continue
            by_weekday[when.weekday()][0] += int(done)
            by_weekday[when.weekday()][1] += 1
            by_month[when.month - 1][0] += int(done)
            by_month[when.month - 1][1] += 1

    scheduled = [h for h in habits if h["today"]["scheduled"]]
    rated = [h["pct"] for h in habits if h["pct"] is not None]
    return {
        "year": year, "today": today.isoformat(), "habits": habits, "colors": COLORS,
        "summary": {
            "count": len(habits),
            "today_done": sum(1 for h in scheduled if h["today"]["done"]), "today_total": len(scheduled),
            "pct": round(sum(rated) / len(rated)) if rated else None,
            "best_streak": max((h["best_streak"] for h in habits), default=0),
            "streak": max((h["streak"] for h in habits), default=0),
        },
        "weeks": weeks,
        "weekdays": [_pct(done, total) for done, total in by_weekday],
        "months": [_pct(done, total) for done, total in by_month],
    }
