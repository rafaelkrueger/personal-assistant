"""Hábitos (cassandra/habits.py): criar, registrar e as contas de consistência."""
from datetime import date, timedelta

import pytest

from cassandra import habits as hb

TODAY = date(2026, 10, 9)  # uma sexta-feira


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(hb, "PATH", tmp_path / "habits.json")
    monkeypatch.setattr(hb, "_today", lambda: TODAY)


def _day(back):
    return (TODAY - timedelta(days=back)).isoformat()


def _get(name):
    return next(h for h in hb.overview()["habits"] if h["name"] == name)


def test_create_edit_and_remove():
    water = hb.save({"name": "  Beber água ", "emoji": "💧", "target": "8", "unit": "copos"})
    assert (water["name"], water["target"], water["period"], water["weekdays"], water["color"]) == (
        "Beber água", 8, "day", [0, 1, 2, 3, 4, 5, 6], hb.COLORS[0])
    gym = hb.save({"name": "Academia", "weekdays": [0, 2, 4, 9, "x"], "target": 0, "period": "mensal"})
    assert (gym["weekdays"], gym["target"], gym["period"], gym["color"]) == ([0, 2, 4], 1, "day", hb.COLORS[1])
    with pytest.raises(ValueError):
        hb.save({"name": "  "})
    edited = hb.save({"id": gym["id"], "name": "Treino", "period": "week", "target": 3})
    assert (edited["name"], edited["period"], edited["weekdays"], edited["created"]) == ("Treino", "week", hb.ALL_DAYS, "2026-10-09")
    with pytest.raises(KeyError):
        hb.save({"id": "nao-existe", "name": "x"})
    assert hb.remove(gym["id"]) is True and hb.remove(gym["id"]) is False
    assert [h["name"] for h in hb.overview()["habits"]] == ["Beber água"]


def test_logging_a_day_sets_adds_and_toggles():
    h = hb.save({"name": "Beber água", "target": 8})
    assert hb.log(h["id"], delta=3) == 3 and hb.log(h["id"], delta=2) == 5
    assert hb.log(h["id"], amount="7,5") == 7.5
    assert hb.log(h["id"], delta=-20) == 0  # nunca fica negativo — e some do registro
    assert hb.log(h["id"], _day(1), toggle=True) == 8 and hb.log(h["id"], _day(1), toggle=True) == 0
    with pytest.raises(ValueError):
        hb.log(h["id"], "2026-10-10", amount=1)  # amanhã
    with pytest.raises(ValueError):
        hb.log(h["id"], "ontem", amount=1)
    with pytest.raises(KeyError):
        hb.log("nao-existe", amount=1)
    assert _get("Beber água")["amounts"] == {}


def test_daily_habit_consistency_and_streaks():
    h = hb.save({"name": "Acordar cedo"})
    for back in (10, 9, 8, 6, 5, 3, 2, 1):  # falhou há 7 e há 4 dias; hoje ainda em aberto
        hb.log(h["id"], _day(back), toggle=True)
    d = _get("Acordar cedo")
    assert (d["start"], d["done_count"], d["total_count"], d["pct"]) == (_day(10), 8, 10, 80)
    assert (d["streak"], d["best_streak"]) == (3, 3)  # hoje em aberto não quebra a sequência
    assert d["today"] == {"amount": 0.0, "scheduled": True, "progress": 0.0, "done": False}
    assert d["cells"][_day(1)] == 1.0 and _day(4) not in d["cells"]
    hb.log(h["id"], toggle=True)
    d = _get("Acordar cedo")
    assert (d["streak"], d["pct"], d["today"]["done"]) == (4, 82, True)  # 9 de 11


def test_partial_days_show_in_the_grid_but_do_not_count_as_done():
    h = hb.save({"name": "Beber água", "target": 8})
    hb.log(h["id"], _day(2), amount=8)
    hb.log(h["id"], _day(1), amount=4)
    d = _get("Beber água")
    assert d["cells"] == {_day(2): 1.0, _day(1): 0.5}
    assert (d["done_count"], d["total_count"], d["streak"]) == (1, 2, 0)


def test_habit_on_some_weekdays_ignores_the_other_days():
    h = hb.save({"name": "Academia", "weekdays": [0, 2, 4]})  # seg, qua, sex
    for back in (11, 9, 4):  # seg 28/09, qua 30/09, seg 05/10 — faltou sex 02/10 e qua 07/10
        hb.log(h["id"], _day(back), toggle=True)
    d = _get("Academia")
    assert (d["done_count"], d["total_count"], d["pct"]) == (3, 5, 60)
    assert (d["streak"], d["best_streak"], d["today"]["scheduled"]) == (0, 2, True)


def test_weekly_habit_counts_weeks():
    h = hb.save({"name": "Ler", "period": "week", "target": 200, "unit": "páginas"})
    hb.log(h["id"], _day(18), amount=120)  # semana de 21/09: 120 + 90 = 210 -> cumprida
    hb.log(h["id"], _day(16), amount=90)
    hb.log(h["id"], _day(9), amount=50)    # semana de 28/09: 50 -> não
    hb.log(h["id"], _day(2), amount=100)   # esta semana (05/10): 100 + 100 = 200 -> cumprida
    hb.log(h["id"], amount=100)
    d = _get("Ler")
    assert (d["done_count"], d["total_count"], d["pct"]) == (2, 3, 67)
    assert (d["streak"], d["best_streak"]) == (1, 1)
    assert d["today"] == {"amount": 100.0, "scheduled": True, "progress": 200.0, "done": True}
    assert d["cells"][_day(18)] == 1.0 and d["cells"][_day(9)] == 1.0  # dia "cheio" = um sétimo da meta
    hb.log(h["id"], amount=0)  # semana em curso e ainda não cumprida: fica fora da conta
    d = _get("Ler")
    assert (d["done_count"], d["total_count"], d["streak"]) == (1, 2, 0)


def test_overview_has_the_summary_and_the_chart_series():
    empty = hb.overview()
    assert empty["summary"] == {"count": 0, "today_done": 0, "today_total": 0, "pct": None, "best_streak": 0, "streak": 0}
    assert len(empty["weeks"]) == 12 and empty["weekdays"] == [None] * 7 and empty["months"] == [None] * 12

    a = hb.save({"name": "Acordar cedo"})
    b = hb.save({"name": "Estudar", "weekdays": [0, 1, 2, 3, 4]})
    for back in range(1, 15):  # A: todo dia nas duas últimas semanas
        hb.log(a["id"], _day(back), toggle=True)
    for back in (4, 3):  # B: só segunda e terça desta semana
        hb.log(b["id"], _day(back), toggle=True)
    hb.log(a["id"], toggle=True)
    o = hb.overview(2026)
    assert o["summary"] == {"count": 2, "today_done": 1, "today_total": 2, "pct": 75, "best_streak": 15, "streak": 15}
    assert (o["year"], o["today"], o["colors"]) == (2026, "2026-10-09", hb.COLORS)
    # esta semana (seg–sex): A 5 de 5; B 2 de 5 (sexta em aberto conta, a semana é medida até hoje) -> 70%
    assert o["weeks"][-1] == {"start": "2026-10-05", "pct": 70}
    assert o["weeks"][-2] == {"start": "2026-09-28", "pct": 100} and o["weeks"][0]["pct"] is None  # B ainda não existia
    assert o["weekdays"][0] == 100 and o["weekdays"][2] == 67  # quartas: A duas vezes, B faltou uma
    assert o["months"][8] == 100 and o["months"][9] == 85 and o["months"][10] is None
    assert hb.overview(1990)["year"] == 2026 and hb.overview(2025)["habits"][0]["cells"] == {}
