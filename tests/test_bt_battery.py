"""Bateria das caixas Bluetooth: a porcentagem vem do BlueZ; "carregando" sai da tendência."""
from cassandra import audio_devices as ad


def test_battery_is_read_from_bluetoothctl_info(monkeypatch):
    monkeypatch.setattr(ad, "_run", lambda cmd, timeout=10: (0, "\tConnected: yes\n\tBattery Percentage: 0x46 (70)\n"))
    assert ad.battery("41:42:9B:1E:A8:01") == 70
    monkeypatch.setattr(ad, "_run", lambda cmd, timeout=10: (0, "\tConnected: yes\n"))
    assert ad.battery("41:42:9B:1E:A8:01") is None


def test_charging_comes_from_the_trend():
    t, mac = ad.BatteryTrend(), "AA"
    t.note(mac, 60, now=0)
    assert t.state(mac, now=10) is None  # uma leitura só: não dá para saber
    t.note(mac, 70, now=600)
    assert t.state(mac, now=700) == "charging"
    assert t.state(mac, now=600 + ad._CHARGING_WINDOW + 1) is None  # parou de subir faz tempo
    t.note(mac, 60, now=5000)
    assert t.state(mac, now=5001) == "discharging"
    t.note(mac, 100, now=6000)
    assert t.state(mac, now=6001) == "full"
    t.note(mac, None)
    assert t.state(mac) is None
