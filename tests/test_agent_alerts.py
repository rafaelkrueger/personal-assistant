"""Os avisos espontâneos dos agentes pessoais: receber, não repetir, juntar e falar fora do silêncio."""
import types
from datetime import datetime, timedelta

import pytest

from cassandra import agent_alerts


@pytest.fixture(autouse=True)
def _tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_alerts, "PATH", tmp_path / "agent_alerts.json")
    monkeypatch.setattr(agent_alerts.conversation_mode, "active", lambda: False)
    monkeypatch.setenv("AGENT_ALERTS_QUIET", "22-8")
    monkeypatch.delenv("AGENT_ALERTS_ENABLED", raising=False)


def _fake_assistant():
    me = types.SimpleNamespace(said=[], _task_thread=None)
    me.announce = lambda text: me.said.append(text) or {"ok": True}
    return me


def _at(hour, minute=0):
    return datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)


def test_receive_validates_and_dedupes():
    with pytest.raises(ValueError):
        agent_alerts.receive("web-agent", [{"key": "x", "text": "y"}])
    with pytest.raises(ValueError):
        agent_alerts.receive("finance", [])
    r = agent_alerts.receive("finance", [{"key": "over-Mercado", "text": "você passou do orçamento de Mercado"},
                                         {"key": "", "text": "sem chave"}, "lixo"])
    assert (r["accepted"], r["skipped"]) == (1, 2)
    # o mesmo aviso de novo, no mesmo dia, não entra
    assert agent_alerts.receive("finance", [{"key": "over-Mercado", "text": "de novo"}])["accepted"] == 0
    # o mesmo key de outro agente é outro aviso
    assert agent_alerts.receive("car", [{"key": "over-Mercado", "text": "outro"}])["accepted"] == 1


def test_compose_one_line_per_agent_most_urgent_first():
    items = [{"agent": "learning", "text": "você ainda não estudou hoje", "level": "soon", "received_at": "1"},
             {"agent": "car", "text": "a troca de óleo venceu", "level": "overdue", "received_at": "2"},
             {"agent": "learning", "text": "há 12 flashcards para revisar.", "level": "soon", "received_at": "3"}]
    assert agent_alerts.compose(items) == ("O Torque avisa: A troca de óleo venceu. "
                                           "O Lume avisa: Você ainda não estudou hoje. Há 12 flashcards para revisar.")


def test_quiet_hours_cross_midnight():
    assert agent_alerts.quiet(_at(23), "22-8") and agent_alerts.quiet(_at(3), "22-8")
    assert not agent_alerts.quiet(_at(8), "22-8") and not agent_alerts.quiet(_at(15), "22-8")
    assert agent_alerts.quiet(_at(13), "12-14") and not agent_alerts.quiet(_at(15), "")


def test_deliver_gathers_then_speaks_once(monkeypatch):
    me = _fake_assistant()
    t0 = _at(10)
    monkeypatch.setattr(agent_alerts, "_now", lambda: t0)
    agent_alerts.receive("finance", [{"key": "a", "text": "gastou demais"}])
    agent_alerts.receive("learning", [{"key": "b", "text": "precisa estudar hoje"}])
    # acabou de chegar: espera um pouco para juntar com o que vier
    assert agent_alerts.deliver(me, now=t0 + timedelta(seconds=10)) == ""
    said = agent_alerts.deliver(me, now=t0 + timedelta(seconds=90))
    assert "A Cifra avisa: Gastou demais." in said and "O Lume avisa: Precisa estudar hoje." in said
    assert me.said == [said]
    assert agent_alerts.deliver(me, now=t0 + timedelta(seconds=200)) == ""  # já foi dito
    assert all(a["spoken_at"] for a in agent_alerts.recent())


def test_deliver_waits_for_quiet_hours_conversation_and_expires(monkeypatch):
    me = _fake_assistant()
    night = _at(23)
    monkeypatch.setattr(agent_alerts, "_now", lambda: night)
    agent_alerts.receive("car", [{"key": "oleo", "text": "a troca de óleo venceu"}])
    assert agent_alerts.deliver(me, now=night + timedelta(minutes=5)) == ""  # silêncio
    morning = night.replace(hour=8, minute=30) + timedelta(days=1)
    monkeypatch.setattr(agent_alerts.conversation_mode, "active", lambda: True)
    assert agent_alerts.deliver(me, now=morning) == ""  # no meio de uma conversa
    monkeypatch.setattr(agent_alerts.conversation_mode, "active", lambda: False)
    assert "troca de óleo" in agent_alerts.deliver(me, now=morning)
    # um aviso que perdeu a validade antes de poder ser dito não é falado
    agent_alerts.receive("learning", [{"key": "hoje", "text": "precisa estudar hoje",
                                       "expires": (night + timedelta(minutes=30)).isoformat()}])
    assert agent_alerts.deliver(me, now=morning + timedelta(days=1)) == ""
    assert agent_alerts.recent()[0]["spoken_at"] == "expirou"


def test_disabled_keeps_receiving_without_speaking(monkeypatch):
    me = _fake_assistant()
    monkeypatch.setenv("AGENT_ALERTS_ENABLED", "0")
    agent_alerts.receive("health", [{"key": "c", "text": "o checkup venceu"}])
    assert agent_alerts.deliver(me, now=_at(12) + timedelta(days=1)) == "" and me.said == []


def test_only_from_home_network():
    assert agent_alerts.from_home({}, "127.0.0.1") and agent_alerts.from_home({}, "192.168.100.52")
    assert not agent_alerts.from_home({}, "8.8.8.8")
    # o túnel entrega como localhost, mas com os cabeçalhos da Cloudflare
    assert not agent_alerts.from_home({"cf-ray": "abc"}, "127.0.0.1")
    assert not agent_alerts.from_home({"x-forwarded-for": "1.2.3.4"}, "127.0.0.1")
