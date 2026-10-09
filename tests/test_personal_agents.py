"""A Cassandra como ponte direta dos agentes pessoais (cassandra/personal_agents.py e agents_bridge.py)."""
import threading
import time

import pytest

from cassandra import agents_bridge, personal_agents as pa


@pytest.fixture()
def net(monkeypatch):
    """Rede simulada: quem está no ar e o que cada rota responde. Guarda as chamadas feitas."""
    state = {"up": {"http://127.0.0.1:8012", "http://127.0.0.1:8014", "http://pc:8015"}, "calls": [], "reply": {}}

    def fake_http(method, url, body=None, timeout=15.0):
        base, _, path = url.partition("/api/")
        path = "/api/" + path
        if base not in state["up"]:
            raise OSError("recusado")
        if path == "/api/health":
            return 200, {"ok": True}
        state["calls"].append((method, base, path, body))
        return state["reply"].get(path, (200, {"reply": "resposta do chat", "text": "texto pronto"}))

    monkeypatch.setattr(pa, "_http", fake_http)
    monkeypatch.setattr(pa, "_alive", {})
    monkeypatch.setenv("CAR_AGENT_URL", "http://127.0.0.1:8015, http://pc:8015/")
    return state


def test_docs_of_every_personal_agent_live_inside_cassandra():
    for name, word in (("health", "Health"), ("finance", "Cifra"), ("car", "Torque")):
        d = pa.docs(name)
        assert word in d["capabilities"] and "/api/chat" in d["api"], name
        assert pa.tagline(d["capabilities"]), name
    assert pa.is_personal("car") and not pa.is_personal("web-agent")


def test_finds_where_each_agent_is_answering(net):
    assert pa.base_url("health") == "http://127.0.0.1:8012"
    assert pa.base_url("car") == "http://pc:8015"  # não está no Pi: cai na segunda URL
    cat = {a["name"]: a for a in pa.catalog()}
    assert [a["status"] for a in cat.values()] == ["online", "online", "online"]
    assert cat["car"]["direct"] is True and cat["finance"]["tagline"].startswith("Finanças pessoais")
    net["up"].discard("http://127.0.0.1:8014")
    assert pa.base_url("finance") == "http://127.0.0.1:8014"  # ainda vale a conferência recente
    assert pa.base_url("finance", fresh=True) is None
    assert [a["name"] for a in pa.online()] == ["health", "car"]


def test_ask_goes_straight_to_the_agent_with_the_same_actions_as_the_maestro(net):
    assert pa.ask("finance", "gastei 45 no mercado") == (True, "resposta do chat")
    assert pa.ask("finance", "gastei 45 no mercado", {"action": "add"}) == (True, "texto pronto")
    assert pa.ask("finance", "", {"action": "Summary", "month": "2026-09"}) == (True, "texto pronto")
    assert pa.ask("car", "", {"action": "status"}, source="finance") == (True, "texto pronto")
    assert pa.ask("health", "como está meu colesterol?", {"action": "overview"}) == (True, "texto pronto")
    assert net["calls"] == [
        ("POST", "http://127.0.0.1:8014", "/api/chat", {"message": "gastei 45 no mercado", "source": "cassandra"}),
        ("POST", "http://127.0.0.1:8014", "/api/transactions/quick", {"text": "gastei 45 no mercado", "source": "cassandra"}),
        ("GET", "http://127.0.0.1:8014", "/api/summary?month=2026-09", None),
        ("GET", "http://pc:8015", "/api/status", None),
        ("POST", "http://127.0.0.1:8012", "/api/overview", {}),
    ]


def test_ask_reports_failures_in_words(net):
    net["reply"]["/api/chat"] = (400, {"detail": "Mensagem vazia."})
    assert pa.ask("health", "x") == (False, "Mensagem vazia.")
    net["up"].clear()
    pa._alive.clear()
    assert pa.ask("finance", "oi") == (False, "a Cifra está fora do ar")
    assert pa.ask("web-agent", "oi")[0] is False


class _Link:
    """Um Maestro simulado: no ar ou não, com os agentes que ele listaria."""
    agent_name = "personal-assistant"
    web_user = ""

    def __init__(self, up, agents=()):
        self.up, self._agents, self.base_url = up, list(agents), ("http://pc:8090" if up else None)

    def available(self):
        return self.up

    def refresh(self):
        return self.base_url

    def agents(self, max_age=30):
        return self._agents

    def usable_agents(self):
        return [a for a in self._agents if a["status"] == "online" and a["name"] != self.agent_name]


def _bridge(monkeypatch, tmp_path, link):
    monkeypatch.setattr(agents_bridge._maestro, "_link", link)
    b = agents_bridge.AgentsBridge(access_path=str(tmp_path / "access.json"))
    b._refresh()
    return b


def test_personal_agents_work_with_the_maestro_off(net, monkeypatch, tmp_path):
    b = _bridge(monkeypatch, tmp_path, _Link(up=False))
    assert b.names() == ["health", "finance", "car"]
    assert "- car (o Torque): O carro do usuário em dia" in b.prompt_block()
    cat = b.catalog()
    assert cat["connected"] is False and [(a["name"], a["direct"], a["status"]) for a in cat["agents"]] == [
        ("health", True, "online"), ("finance", True, "online"), ("car", True, "online")]
    reply = b.run("car", "como está o carro?", 5, parameters={"action": "status"})
    assert (reply.ok, reply.text) == (True, "texto pronto")
    assert net["calls"] == [("GET", "http://pc:8015", "/api/status", None)]  # nada passou pelo Maestro
    assert b.run("web-agent", "pesquise x", 1).error.startswith("o Maestro está desligado")
    b.set_allowed("finance", False)
    b._refresh()
    assert b.names() == ["health", "car"]


def test_with_the_maestro_on_personal_ones_are_still_direct(net, monkeypatch, tmp_path):
    listed = [{"name": "web-agent", "status": "online", "tagline": "Navega", "description": ""},
              {"name": "finance", "status": "offline", "tagline": "versão do Maestro", "description": ""},
              {"name": "personal-assistant", "status": "online", "tagline": "", "description": ""}]
    b = _bridge(monkeypatch, tmp_path, _Link(up=True, agents=listed))
    assert b.names() == ["health", "finance", "car", "web-agent"]  # a Cifra vem direto, não a listada pelo Maestro
    cat = {a["name"]: a for a in b.catalog()["agents"]}
    assert set(cat) == {"health", "finance", "car", "web-agent"} and cat["web-agent"]["direct"] is False
    assert cat["finance"]["tagline"].startswith("Finanças pessoais")


def test_slow_personal_agent_answers_later_instead_of_blocking_the_talk(net, monkeypatch, tmp_path):
    b = _bridge(monkeypatch, tmp_path, _Link(up=False))
    release, late = threading.Event(), []

    def slow_ask(name, task, parameters=None, **kw):
        release.wait(5)
        return True, "resultado demorado"

    monkeypatch.setattr(pa, "ask", slow_ask)
    reply = b.run("health", "panorama", 0.2, on_late_result=lambda t, r: late.append((t, r.ok, r.text)))
    assert reply.pending is True and late == []
    release.set()
    for _ in range(50):
        if late:
            break
        time.sleep(0.05)
    assert late == [("health", True, "resultado demorado")]
