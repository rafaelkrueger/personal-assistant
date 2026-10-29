import pytest

from cassandra import audio_routes


@pytest.fixture
def routes(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_routes, "ROUTES_FILE", tmp_path / "audio_routes.json")
    monkeypatch.setattr(audio_routes, "options", lambda: audio_routes.load())
    applied = []
    monkeypatch.setattr(audio_routes, "_apply_voice", lambda v: applied.append(("voice", v)))
    monkeypatch.setattr(audio_routes, "_apply_music", lambda v: applied.append(("music", v)))
    return applied


def test_defaults(routes):
    assert audio_routes.load() == {"mic": "auto", "voice": "auto", "music": "same"}


def test_set_each_route(routes):
    result = audio_routes.set_routes({"mic": "bt:41:42:9b:1e:a8:01", "voice": "node:alsa_output.x",
                                      "music": "bt:4C:6B:B8:DE:E4:FC"})
    assert result == {"mic": "bt:41:42:9B:1E:A8:01", "voice": "node:alsa_output.x", "music": "bt:4C:6B:B8:DE:E4:FC"}
    assert routes == [("voice", "node:alsa_output.x"), ("music", "bt:4C:6B:B8:DE:E4:FC")]


def test_invalid_values(routes):
    for patch in ({"mic": "node:alsa_input.x"}, {"voice": "same"}, {"music": "usb"}, {"mic": "bt:zz"}):
        with pytest.raises(audio_routes.RouteError):
            audio_routes.set_routes(patch)


def test_mic_choice_picks_the_chosen_bluetooth(routes, monkeypatch):
    monkeypatch.setattr(audio_routes, "_bt_inputs",
                        lambda: ["bluez_input.4C:6B:B8:DE:E4:FC", "bluez_input.41:42:9B:1E:A8:01"])
    monkeypatch.setattr(audio_routes.glob, "glob", lambda pattern: [])
    assert audio_routes.bluetooth_mic_input() == "bluez_input.4C:6B:B8:DE:E4:FC"  # auto sem USB: o 1º
    monkeypatch.setattr(audio_routes.glob, "glob", lambda pattern: ["/proc/asound/card2/pcm0c"])
    assert audio_routes.bluetooth_mic_input() is None  # auto com USB: fica no USB
    audio_routes.set_routes({"mic": "bt:41:42:9B:1E:A8:01"})
    assert audio_routes.bluetooth_mic_input() == "bluez_input.41:42:9B:1E:A8:01"
    audio_routes.set_routes({"mic": "usb"})
    assert audio_routes.bluetooth_mic_input() is None
    audio_routes.set_routes({"mic": "bt:00:11:22:33:44:55"})  # escolhido, mas desligado: fica no USB
    assert audio_routes.bluetooth_mic_input() is None


def test_voice_allows_eq_default(routes):
    assert audio_routes.voice_allows_default("4C:6B:B8:DE:E4:FC")
    audio_routes.set_routes({"voice": "bt:41:42:9B:1E:A8:01"})
    assert not audio_routes.voice_allows_default("4C:6B:B8:DE:E4:FC")
    assert audio_routes.voice_allows_default("41:42:9b:1e:a8:01")


def test_keeps_chosen_bluetooth_awake(routes, monkeypatch):
    calls = []
    monkeypatch.setattr(audio_routes.subprocess, "run", lambda cmd, **kw: calls.append(cmd[:2]))
    monkeypatch.setattr(audio_routes, "_last_keepalive", {})
    monkeypatch.setattr(audio_routes, "_last_reconnect", {})
    sinks = {"41:42:9B:1E:A8:01": {"id": 1, "name": "bluez_output.41_42_9B_1E_A8_01.1"}}
    monkeypatch.setattr(audio_routes, "bt_sink", lambda mac: sinks.get(mac))
    routes_ = {"mic": "usb", "voice": "bt:41:42:9B:1E:A8:01", "music": "bt:4C:6B:B8:DE:E4:FC"}
    audio_routes._keep_bt_awake(routes_)
    assert sorted(calls) == [["bluetoothctl", "connect"], ["pw-play", "--target"]]
    audio_routes._keep_bt_awake(routes_)  # logo em seguida: nada de novo
    assert len(calls) == 2
