"""Pedidos falados como a transcrição devolve: horários e durações por extenso, perguntas e o item depois do verbo."""
from datetime import date, timedelta

import pytest

from skills import spoken
from skills.alarm.skill import AlarmSkill
from skills.shopping_list.skill import ShoppingListSkill
from skills.timer.skill import TimerSkill
from skills.todo.skill import TodoSkill


@pytest.mark.parametrize("text, hhmm", [
    ("Coloca um alarme pras seis e meia.", "06:30"),
    ("alarme às 7h30", "07:30"),
    ("me acorda às sete da manhã", "07:00"),
    ("alarme às duas da tarde", "14:00"),
    ("alarme dez para as oito", "07:50"),
    ("alarme ao meio-dia", "12:00"),
    ("alarme à meia-noite e meia", "00:30"),
    ("alarme às 19:45", "19:45"),
    ("alarme dia 15 às 7", "07:00"),
    ("boa noite, alarme às 7", "07:00"),  # "boa noite" não é "da noite"
    ("alarme às 11 da noite", "23:00"),
    ("alarme pras vinte e uma e quinze", "21:15"),
    ("alarme 7 horas e 15 minutos", "07:15"),
    ("hoje à noite às 9", "21:00"),
    ("alarme para o dia 15", None),  # data não é horário
])
def test_spoken_times(text, hhmm):
    assert spoken.time_of_day(text) == hhmm


@pytest.mark.parametrize("text, seconds", [
    ("timer de cinco minutos", 300),
    ("meia hora", 1800),
    ("uma hora e meia", 5400),
    ("um minuto e meio", 90),
    ("1h30", 5400),
    ("dois minutos e trinta segundos", 150),
    ("vinte e cinco minutos", 1500),
    ("1 hora e 30 minutos", 5400),
    ("1 hora e 30", 5400),
    ("timer de 5", 300),
    ("cento e vinte segundos", 120),
])
def test_spoken_durations(text, seconds):
    assert spoken.duration_seconds(text) == seconds


class _Alarms:
    def __init__(self):
        self.added = []
        self.alarms = []

    def add_alarm(self, when, **kw):
        self.added.append((when, kw))
        return type("A", (), {"time_hhmm": when})()

    def list_alarms(self):
        return self.alarms

    def stop_ringing(self):
        return False


def test_alarm_understands_spoken_times_dates_and_reminders():
    am = _Alarms()
    skill = AlarmSkill(am)
    assert skill.can_handle("Me acorda amanhã às seis e meia")
    assert "06:30" in skill.handle("Me acorda amanhã às seis e meia")
    when, kw = am.added[-1]
    assert when == "06:30" and kw["date_ymd"] == (date.today() + timedelta(days=1)).isoformat()  # amanhã, não hoje
    assert skill.can_handle("Me lembra de tomar o remédio às oito da noite")
    reply = skill.handle("Me lembra de tomar o remédio às oito da noite")
    assert am.added[-1][0] == "20:00" and am.added[-1][1]["label"] == "tomar o remédio" and "tomar o remédio" in reply
    skill.handle("alarme às 7 de segunda a sexta")
    assert am.added[-1][1]["days_of_week"] == [0, 1, 2, 3, 4]


def test_a_question_about_alarms_lists_them():
    am = _Alarms()
    today = date.today()
    am.alarms = [
        {"time_hhmm": "07:00", "days_of_week": None, "recurring_daily": True, "enabled": True, "label": "x"},
        {"time_hhmm": "09:00", "days_of_week": None, "recurring_daily": False, "enabled": True, "label": "x",
         "next_trigger_at": (today + timedelta(days=3)).isoformat() + "T09:00:00"},
    ]
    skill = AlarmSkill(am)
    reply = skill.handle("Eu tenho algum alarme pra hoje?")  # antes: "Nao entendi o horario"
    assert "07:00" in reply and "09:00" not in reply and not am.added
    assert "09:00" in skill.handle("Quais alarmes eu tenho?")
    am.alarms = []
    assert "amanhã" in skill.handle("Tenho alarme amanhã?")
    skill.handle("Alarme às 7?")  # entonação de pergunta, mas com horário: é criar
    assert am.added and am.added[-1][0] == "07:00"


def test_timer_takes_durations_and_leaves_clock_times_to_the_alarm():
    timer = TimerSkill(type("TM", (), {"add": lambda self, name, seconds: None, "active_names": lambda self: []})())
    assert timer.can_handle("me lembra daqui a dez minutos de tirar o bolo")
    assert "10 minutos" in timer.handle("me lembra daqui a dez minutos de tirar o bolo")
    assert "1 hora e 30" in timer.handle("timer de uma hora e meia")
    assert not timer.can_handle("me lembra de tomar o remédio às oito")  # antes: timer de 8 minutos
    assert AlarmSkill(_Alarms()).can_handle("me lembra de tomar o remédio às oito")
    assert not AlarmSkill(_Alarms()).can_handle("me lembra daqui a dez minutos de tirar o bolo")


def test_shopping_list_takes_the_whole_verb_and_several_items(tmp_path):
    skill = ShoppingListSkill(str(tmp_path / "compras.json"))
    assert skill.handle("Adicionar leite na lista de compras.") == "Adicionado na lista de compras: leite."
    assert skill.handle("Coloca pão, manteiga e ovos na lista de compras") == \
        "Adicionado na lista de compras: pão, manteiga e ovos."
    assert skill.handle("Põe arroz à lista de compras, por favor") == "Adicionado na lista de compras: arroz."
    assert [i["name"] for i in skill.list_items()] == ["leite", "pão", "manteiga", "ovos", "arroz"]
    assert skill.handle("Tira o pao da lista de compras") == "Removido da lista de compras: pao."  # sem acento
    assert "pão" not in [i["name"] for i in skill.list_items()]
    assert skill.can_handle("adiciona café na lista do mercado")


def test_todo_list_takes_the_whole_verb(tmp_path):
    skill = TodoSkill(str(tmp_path / "tarefas.json"))
    assert skill.handle("Adicionar pagar luz na lista de tarefas.") == "Tarefa adicionada: pagar luz."
    assert skill.handle("adiciona terminar o relatório na lista de tarefas") == \
        "Tarefa adicionada: terminar o relatório."  # "terminar" é a tarefa, não "concluir"
    assert skill.handle("marca pagar luz como feita na lista de tarefas") == "Tarefa marcada como concluida: pagar luz."
    assert skill.handle("remove terminar o relatório da lista de tarefas") == \
        "Tarefa removida: terminar o relatório."


def test_numbers_by_word():
    assert spoken.numbers("vinte e cinco") == "25"
    assert spoken.numbers("cento e vinte e cinco") == "125"
    assert spoken.numbers("sete e meia") == "7 e meia"
    assert spoken.numbers("cinco e vinte") == "5 e 20"  # "cinco e vinte" não é um número só
