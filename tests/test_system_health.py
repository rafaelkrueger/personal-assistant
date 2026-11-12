"""Saúde do Pi (cassandra/system_health.py): leitura dos números e o veredito."""
from cassandra import system_health as sh


def test_parsers():
    mi = sh.parse_meminfo("MemTotal:  926720 kB\nMemAvailable:  223232 kB\nSwapTotal: 925692 kB\nSwapFree: 692224 kB\n")
    assert mi["MemTotal"] == 926720 * 1024 and mi["MemAvailable"] == 223232 * 1024
    assert sh.parse_cpu_line("cpu  100 0 50 800 50 0 0 0 0 0\ncpu0 1 2 3 4\n") == (850, 1000)
    assert sh.parse_throttled("throttled=0xd0005\n") == 0xD0005
    assert sh.parse_throttled("") is None
    now, past = sh.throttle_reasons(0xD0005)
    assert now[0].startswith("Subtensão agora") and len(now) == 2
    assert past[0].startswith("Teve subtensão") and len(past) == 3
    top = sh.parse_ps("209813504 26,3 /home/x/.venv/bin/python main.py\n 72712 3.4 /h/health/.venv/bin/python -m uvicorn app.main:app\n")
    assert top[0]["name"] == "Cassandra" and top[0]["cpu"] == 26.3
    assert top[1]["name"] == "Pulse" and top[1]["memory"] == 72712 * 1024


def _base(**kw):
    d = {"memory": {"total": 1000, "available": 500, "used": 500}, "swap": {"total": 1000, "used": 100},
         "disk": {"total": 100, "used": 30}, "temp_c": 50.0, "throttle_now": [], "throttle_past": [],
         "load": [0.5, 0.5, 0.5], "cores": 4, "services": [{"id": "cassandra-assistant", "label": "Cassandra", "state": "active"}]}
    d.update(kw)
    return d


def test_judge_levels():
    assert sh.judge(_base()) == ("ok", [])
    level, issues = sh.judge(_base(memory={"total": 1000, "available": 150, "used": 850}, temp_c=72.0))
    assert level == "warn" and len(issues) == 2
    level, issues = sh.judge(_base(throttle_now=["Subtensão agora: a fonte não está dando conta"]))
    assert level == "bad"
    level, _ = sh.judge(_base(services=[{"id": "cassandra-assistant", "label": "Cassandra", "state": "failed"}]))
    assert level == "bad"
    level, issues = sh.judge(_base(throttle_past=["Teve subtensão desde que ligou (fonte fraca)"]))
    assert level == "warn" and "fonte" in issues[0]["text"]
