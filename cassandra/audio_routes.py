"""Qual aparelho a Cassandra usa para cada coisa: microfone, voz (respostas, alarmes e bipes) e música (Spotify).

- voz: a saída padrão do PipeWire — tudo que ela toca com o pw-play vai para lá.
- música: o Spotify Connect "Cassandra" (librespot) toca numa saída própria. O cassandra-spotify.sh lê
  ~/.config/cassandra/music-output (o nome da saída no PipeWire) e passa em PULSE_SINK; trocar reinicia o serviço.
  Se a saída escolhida não existir (caixa desligada), o PipeWire toca na saída padrão.
- microfone: o VadRecorder pergunta mic_choice() — USB pelo PyAudio, ou a entrada viva-voz de um aparelho Bluetooth.
  Microfone Bluetooth só quando escolhido (ou sem USB): ele deixa o som da caixa em qualidade de telefone (baixo,
  mono, com chiado) — o Bluetooth não tem microfone e som de alta qualidade ao mesmo tempo.

As escolhas ficam em data/audio_routes.json: {"mic": "auto"|"usb"|"bt:MAC", "voice": "auto"|"bt:MAC"|"node:<nome>",
"music": "same"|"bt:MAC"|"node:<nome>"}. Um aparelho Bluetooth desconectado volta a valer quando reconectar: o vigia
do bt_audio chama enforce() a cada 10 s.
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from cassandra import audio_devices
from cassandra.bt_audio import EQ_NODE, _default_sink_name, _eq_of, _node_by_name, _nodes, bt_audio, bt_sink

ROUTES_FILE = Path("data/audio_routes.json")
MUSIC_FILE = Path("~/.config/cassandra/music-output").expanduser()
MUSIC_SERVICE = os.getenv("SPOTIFY_LIBRESPOT_SERVICE", "cassandra-spotify")
DEFAULTS = {"mic": os.getenv("MIC_SOURCE", "auto").strip().lower() or "auto", "voice": "auto", "music": "same"}


class RouteError(Exception):
    pass


def load() -> dict[str, str]:
    try:
        data = json.loads(ROUTES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {k: str(data.get(k) or v) for k, v in DEFAULTS.items()}


def _save(routes: dict[str, str]) -> None:
    ROUTES_FILE.parent.mkdir(parents=True, exist_ok=True)
    ROUTES_FILE.write_text(json.dumps(routes, indent=2), encoding="utf-8")


def mic_choice() -> str:
    return load()["mic"]


# ── o que existe ──────────────────────────────────────────────────────────────

def _bt_info(mac: str) -> str:
    try:
        return subprocess.run(["bluetoothctl", "info", mac], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _bt_audio_devices() -> list[dict[str, Any]]:
    """Aparelhos Bluetooth pareados que tocam som; has_mic = têm viva-voz (Handsfree/Headset)."""
    out = []
    for mac, name in audio_devices._devices("Paired").items():
        info = _bt_info(mac)
        if "Audio Sink" not in info:
            continue
        out.append({"mac": mac, "name": name, "has_mic": bool(re.search(r"UUID: (Handsfree|Headset) ", info))})
    return out


def _bt_inputs() -> list[str]:
    """Entradas viva-voz dos aparelhos Bluetooth conectados, ex. "bluez_input.41:42:9B:1E:A8:01"."""
    try:
        out = subprocess.run(["wpctl", "status", "--name"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return re.findall(r"\b(bluez_input\.[0-9A-Fa-f:]{17})\b", out)


def bluetooth_mic_input() -> str | None:
    """A entrada Bluetooth que o microfone deve usar agora (None = microfone USB)."""
    choice = mic_choice()
    if choice == "usb":
        return None
    inputs = _bt_inputs()
    if choice.startswith("bt:"):
        want = "bluez_input." + choice[3:].upper()
        return next((i for i in inputs if i.upper() == want.upper()), None)
    if glob.glob("/proc/asound/card*/pcm*c"):
        return None  # automático: com microfone USB, fica nele
    return inputs[0] if inputs else None


def _pi_sinks(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Saídas que não são Bluetooth nem o equalizador (HDMI/fone do próprio Pi, placa USB...)."""
    sinks = []
    for n in nodes:
        p = n["props"]
        if p.get("media.class") != "Audio/Sink" or p.get("node.name") == EQ_NODE or p.get("api.bluez5.address"):
            continue
        label = p.get("node.description") or p.get("node.name")
        if str(p.get("node.name", "")).startswith("alsa_output.platform-"):
            label = "Saída do próprio Pi (HDMI / fone)"
        sinks.append({"value": "node:" + p["node.name"], "label": label, "available": True})
    return sinks


def options() -> dict[str, Any]:
    routes = load()
    nodes = _nodes()
    bt = _bt_audio_devices()
    connected = {str(n["props"].get("api.bluez5.address", "")).upper() for n in nodes
                 if n["props"].get("media.class") == "Audio/Sink" and n["props"].get("api.bluez5.address")}
    inputs = {i.split(".", 1)[1].upper() for i in _bt_inputs()}
    bt_out = [{"value": "bt:" + d["mac"], "label": d["name"], "available": d["mac"] in connected} for d in bt]
    pi = _pi_sinks(nodes)
    usb_present = bool(glob.glob("/proc/asound/card*/pcm*c"))
    mic_opts = [{"value": "auto", "label": "Automático (o USB; sem ele, um Bluetooth com viva-voz)",
                 "available": True},
                {"value": "usb", "label": "Microfone USB", "available": usb_present}]
    mic_opts += [{"value": "bt:" + d["mac"], "label": f"{d['name']} (viva-voz: som dela vira qualidade de telefone)", "available": d["mac"] in inputs}
                 for d in bt if d["has_mic"]]
    voice_opts = [{"value": "auto", "label": "Saída padrão do Pi", "available": True}, *bt_out, *pi]
    music_opts = [{"value": "same", "label": "A mesma da voz", "available": True}, *bt_out, *pi]
    for opts, key in ((mic_opts, "mic"), (voice_opts, "voice"), (music_opts, "music")):
        if not any(o["value"] == routes[key] for o in opts):  # aparelho esquecido/sumido: mostra a escolha mesmo assim
            opts.append({"value": routes[key], "label": routes[key].split(":", 1)[-1], "available": False})

    default = _default_sink_name()
    default_label = next((n["props"].get("node.description") for n in nodes
                          if n["props"].get("node.name") == default), default)
    if default == EQ_NODE:
        default_label = "equalizador da caixa Bluetooth"
    mic_now = bluetooth_mic_input()
    view = {
        "mic": {"value": routes["mic"], "options": mic_opts,
                "now": f"Bluetooth ({mic_now.split('.', 1)[1]})" if mic_now else ("microfone USB" if usb_present else "nenhum")},
        "voice": {"value": routes["voice"], "options": voice_opts, "now": default_label or "—"},
        "music": {"value": routes["music"], "options": music_opts,
                  "now": "a mesma da voz" if routes["music"] == "same" else _label_of(routes["music"], music_opts)},
    }
    if mic_now:
        mac = mic_now.split(".", 1)[1].upper()
        name = next((d["name"] for d in bt if d["mac"] == mac), mac)
        view["note"] = (f"Com o microfone da {name} em uso, o som que vai para ela fica em qualidade de telefone "
                        "(mono, abafado): o Bluetooth não deixa usar microfone e som de alta qualidade ao mesmo tempo.")
    return view


def _label_of(value: str, opts: list[dict[str, Any]]) -> str:
    return next((o["label"] for o in opts if o["value"] == value), value)


# ── aplicar ───────────────────────────────────────────────────────────────────

def set_routes(patch: dict[str, Any]) -> dict[str, Any]:
    routes = load()
    for key in ("mic", "voice", "music"):
        if key not in patch:
            continue
        value = str(patch[key] or "").strip()
        if re.fullmatch(r"(?i)bt:[0-9a-f:]{17}", value):
            value = "bt:" + value[3:].upper()
        elif value not in {"mic": ("auto", "usb"), "voice": ("auto",), "music": ("same",)}[key] and not (
                key != "mic" and value.startswith("node:")):
            raise RouteError(f"opção inválida para {key}: {value}")
        routes[key] = value
    _save(routes)
    if "voice" in patch:
        _apply_voice(routes["voice"])
    if "music" in patch:
        _apply_music(routes["music"])
    return options()


def _apply_voice(voice: str) -> None:
    """Faz da saída escolhida a padrão (se ela estiver ligada agora)."""
    default = _default_sink_name()
    if voice.startswith("bt:"):
        mac = voice[3:]
        sink = bt_sink(mac)
        if not sink:
            return  # desconectada: o vigia aplica quando ela voltar
        using_eq = default == EQ_NODE and bt_audio._eq_mac == mac
        if default != sink["name"] and not using_eq:
            bt_audio.use_as_output(mac)
    elif voice.startswith("node:"):
        node = _node_by_name(voice[5:])
        if node and default != voice[5:]:
            subprocess.run(["wpctl", "set-default", str(node["id"])], capture_output=True, timeout=10)


def _music_sink_name(music: str) -> str | None:
    if music.startswith("node:"):
        return music[5:]
    if music.startswith("bt:"):
        mac = music[3:]
        if _eq_of(mac).get("enabled"):
            return EQ_NODE  # com o equalizador ligado, a música passa por ele (grave/agudo)
        sink = bt_sink(mac)
        return sink["name"] if sink else f"bluez_output.{mac.replace(':', '_')}.1"
    return None  # "same": a saída padrão


def _apply_music(music: str) -> None:
    """Grava a saída da música para o librespot e o reinicia se ela mudou."""
    target = _music_sink_name(music)
    try:
        current = MUSIC_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        current = ""
    if (target or "") == current:
        return
    MUSIC_FILE.parent.mkdir(parents=True, exist_ok=True)
    if target:
        MUSIC_FILE.write_text(target + "\n", encoding="utf-8")
    else:
        MUSIC_FILE.unlink(missing_ok=True)
    subprocess.run(["systemctl", "--user", "restart", MUSIC_SERVICE], capture_output=True, timeout=20)


def voice_allows_default(mac: str) -> bool:
    """O equalizador desta caixa pode virar a saída padrão? (Só se a voz não foi mandada para outro aparelho.)"""
    voice = load()["voice"]
    return voice == "auto" or voice.upper() == f"BT:{mac.upper()}"


def enforce() -> None:
    """Chamado pelo vigia do bt_audio: reaplica a voz (ex.: a caixa escolhida acabou de reconectar)."""
    routes = load()
    if routes["voice"] != "auto":
        _apply_voice(routes["voice"])
    _keep_bt_awake(routes)


# ── caixas Bluetooth que desligam sozinhas ────────────────────────────────────
# Caixas baratas se desligam após alguns minutos sem som (e somem do Pi). Para as caixas escolhidas para voz ou
# música: um sopro inaudível (ruído a ~-70 dBFS, 1 s) a cada KEEPALIVE_S segundos as mantém acordadas, e uma caixa
# escolhida que caiu é reconectada a cada RECONNECT_S segundos (se estiver ligada, volta sozinha).
KEEPALIVE_S = float(os.getenv("BT_KEEPALIVE_S", "240") or 0)
RECONNECT_S = float(os.getenv("BT_RECONNECT_S", "60") or 0)
_last_keepalive: dict[str, float] = {}
_last_reconnect: dict[str, float] = {}


def _whisper() -> bytes:
    """1 s de ruído baixíssimo (48 kHz, mono, s16): inaudível, mas a caixa entende que está tocando."""
    import numpy as np  # noqa: PLC0415

    return np.random.randint(-6, 7, 48000, dtype=np.int16).tobytes()


def _keep_bt_awake(routes: dict[str, str]) -> None:
    now = time.monotonic()
    macs = {r[3:] for r in (routes["voice"], routes["music"]) if r.startswith("bt:")}
    for mac in macs:
        sink = bt_sink(mac)
        if not sink:
            if RECONNECT_S and now - _last_reconnect.get(mac, 0) >= RECONNECT_S:
                _last_reconnect[mac] = now
                subprocess.run(["bluetoothctl", "connect", mac], capture_output=True, timeout=20)
            continue
        if KEEPALIVE_S and now - _last_keepalive.get(mac, 0) >= KEEPALIVE_S:
            _last_keepalive[mac] = now
            subprocess.run(["pw-play", "--target", str(sink["name"]), "--rate", "48000", "--channels", "1",
                            "--format", "s16", "--raw", "-"], input=_whisper(), capture_output=True, timeout=10)
