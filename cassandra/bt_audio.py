"""Controle de caixas de som/fones Bluetooth conectados: volume e mudo da própria caixa, usar como saída e um
equalizador (grave e agudo) aplicado pelo Pi no som que vai para ela.

O que o Bluetooth permite: a caixa se conecta como saída de áudio (A2DP) e controle remoto (AVRCP) — o volume
mexido aqui é o volume absoluto da própria caixa. Ajustes internos da caixa (ex.: os modos de som e o grave do
app LG Sound Bar) usam protocolos proprietários do fabricante, que não são públicos; por isso o grave/agudo é
feito pelo Pi: um filtro do PipeWire (filter-chain, bq_lowshelf + bq_highshelf) entre os apps e a caixa.

O filtro roda como serviço do usuário (cassandra-eq.service, `pipewire -c ~/.config/cassandra/eq.conf`) e vira a
saída padrão enquanto está ligado. Um vigia a cada 10 s: se a caixa sumir, volta a saída normal (o som nunca
some); se ela voltar com o equalizador ligado, religa o filtro.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

EQ_FILE = Path("data/eq.json")  # {mac: {"enabled": bool, "bass": dB, "treble": dB}}
EQ_CONF = Path("~/.config/cassandra/eq.conf").expanduser()
EQ_SERVICE = "cassandra-eq"
EQ_UNIT = Path(f"~/.config/systemd/user/{EQ_SERVICE}.service").expanduser()
EQ_NODE = "cassandra_eq"
GAIN_LIMIT = 12.0

PRESETS = {
    "normal": (0.0, 0.0),
    "grave": (7.0, 0.0),
    "grave_forte": (11.0, 2.0),
    "voz": (-3.0, 4.0),
    "agudo": (0.0, 6.0),
}


def _run(cmd: list[str], timeout: float = 10) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


def _nodes() -> list[dict[str, Any]]:
    code, out = _run(["pw-dump"], timeout=10)
    if code != 0:
        return []
    try:
        data = json.loads(out)
    except ValueError:
        return []
    nodes = []
    for obj in data:
        if obj.get("type") != "PipeWire:Interface:Node":
            continue
        props = (obj.get("info") or {}).get("props") or {}
        nodes.append({"id": obj.get("id"), "props": props})
    return nodes


def bt_sink(mac: str) -> dict[str, Any] | None:
    """A saída de áudio (sink) do PipeWire daquele aparelho Bluetooth, se estiver conectado."""
    mac = mac.upper()
    for n in _nodes():
        p = n["props"]
        if p.get("media.class") == "Audio/Sink" and str(p.get("api.bluez5.address", "")).upper() == mac:
            return {"id": n["id"], "name": p.get("node.name"), "description": p.get("node.description")}
    return None


def _node_by_name(name: str) -> dict[str, Any] | None:
    return next(({"id": n["id"], "props": n["props"]} for n in _nodes() if n["props"].get("node.name") == name), None)


def _default_sink_name() -> str:
    code, out = _run(["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"])
    for line in out.splitlines():
        if "node.name" in line and "=" in line:
            return line.split("=", 1)[1].strip().strip('"')
    return ""


def _volume(node_id: int) -> tuple[int | None, bool]:
    code, out = _run(["wpctl", "get-volume", str(node_id)])
    try:
        value = round(float(out.split("Volume:")[1].split()[0]) * 100)
    except (IndexError, ValueError):
        value = None
    return value, "MUTED" in out


def _load_eq() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(EQ_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_eq(data: dict[str, dict[str, Any]]) -> None:
    EQ_FILE.parent.mkdir(parents=True, exist_ok=True)
    EQ_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _eq_of(mac: str) -> dict[str, Any]:
    return {"enabled": False, "bass": 0.0, "treble": 0.0, **_load_eq().get(mac.upper(), {})}


class BtAudio:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._eq_mac: str | None = None  # para qual caixa o filtro está rodando agora
        self._watch: threading.Thread | None = None

    # ── estado ──
    def state(self, mac: str) -> dict[str, Any]:
        mac = mac.upper()
        sink = bt_sink(mac)
        eq = _eq_of(mac)
        view: dict[str, Any] = {"mac": mac, "connected": bool(sink), "eq": eq, "presets": list(PRESETS)}
        if sink:
            volume, muted = _volume(sink["id"])
            default = _default_sink_name()
            view.update({"volume": volume, "muted": muted, "name": sink["description"],
                         "is_output": default == sink["name"] or (default == EQ_NODE and self._eq_mac == mac),
                         "eq_running": self._eq_mac == mac and bool(_node_by_name(EQ_NODE))})
        return view

    # ── volume / mudo / saída ──
    def set_volume(self, mac: str, pct: int) -> None:
        sink = self._need_sink(mac)
        pct = max(0, min(100, int(pct)))
        _run(["wpctl", "set-volume", str(sink["id"]), f"{pct / 100:.2f}"])

    def set_mute(self, mac: str, muted: bool) -> None:
        sink = self._need_sink(mac)
        _run(["wpctl", "set-mute", str(sink["id"]), "1" if muted else "0"])

    def use_as_output(self, mac: str) -> None:
        sink = self._need_sink(mac)
        if _eq_of(mac)["enabled"]:
            self._start_eq(mac, sink)
        else:
            _run(["wpctl", "set-default", str(sink["id"])])

    @staticmethod
    def _need_sink(mac: str) -> dict[str, Any]:
        sink = bt_sink(mac)
        if not sink:
            raise RuntimeError("a caixa não está conectada")
        return sink

    # ── equalizador ──
    def set_eq(self, mac: str, enabled: bool | None = None, bass: float | None = None,
               treble: float | None = None, preset: str | None = None) -> None:
        mac = mac.upper()
        data = _load_eq()
        eq = {"enabled": False, "bass": 0.0, "treble": 0.0, **data.get(mac, {})}
        if preset in PRESETS:
            eq["bass"], eq["treble"] = PRESETS[preset]
            eq["enabled"] = True
        if bass is not None:
            eq["bass"] = max(-GAIN_LIMIT, min(GAIN_LIMIT, float(bass)))
        if treble is not None:
            eq["treble"] = max(-GAIN_LIMIT, min(GAIN_LIMIT, float(treble)))
        if enabled is not None:
            eq["enabled"] = bool(enabled)
        elif bass is not None or treble is not None:
            eq["enabled"] = True
        data[mac] = eq
        _save_eq(data)
        sink = bt_sink(mac)
        if eq["enabled"] and sink:
            if self._eq_mac == mac and _node_by_name(EQ_NODE):
                self._apply_gains(eq)
            else:
                self._start_eq(mac, sink)
        elif not eq["enabled"] and self._eq_mac == mac:
            self._stop_eq(fallback=sink)

    def _write_conf(self, target: str) -> None:
        EQ_CONF.parent.mkdir(parents=True, exist_ok=True)
        EQ_CONF.write_text(f"""# Gerado pela Cassandra (cassandra/bt_audio.py): grave/agudo para a caixa Bluetooth.
context.properties = {{ log.level = 0 }}
context.spa-libs = {{ audio.convert.* = audioconvert/libspa-audioconvert  support.* = support/libspa-support }}
context.modules = [
  {{ name = libpipewire-module-rt  flags = [ ifexists nofail ] }}
  {{ name = libpipewire-module-protocol-native }}
  {{ name = libpipewire-module-client-node }}
  {{ name = libpipewire-module-adapter }}
  {{ name = libpipewire-module-filter-chain
    args = {{
      node.description = "Cassandra — equalizador"
      media.name = "Cassandra EQ"
      filter.graph = {{
        nodes = [
          {{ type = builtin name = bass label = bq_lowshelf control = {{ "Freq" = 120.0 "Q" = 0.7 "Gain" = 0.0 }} }}
          {{ type = builtin name = treble label = bq_highshelf control = {{ "Freq" = 6000.0 "Q" = 0.7 "Gain" = 0.0 }} }}
        ]
        links = [ {{ output = "bass:Out" input = "treble:In" }} ]
      }}
      audio.channels = 2
      audio.position = [ FL FR ]
      capture.props = {{ node.name = "{EQ_NODE}" media.class = Audio/Sink
                         session.suspend-timeout-seconds = 0 node.pause-on-idle = false }}
      playback.props = {{ node.name = "{EQ_NODE}.output" node.passive = true target.object = "{target}"
                          session.suspend-timeout-seconds = 0 node.pause-on-idle = false }}
    }}
  }}
]
""", encoding="utf-8")
        if not EQ_UNIT.exists():
            EQ_UNIT.parent.mkdir(parents=True, exist_ok=True)
            EQ_UNIT.write_text(f"""# Equalizador da Cassandra para a caixa Bluetooth (ligado/desligado pela própria Cassandra).
[Unit]
Description=Cassandra - equalizador da caixa Bluetooth (PipeWire filter-chain)
After=pipewire.service

[Service]
Type=simple
ExecStart=/usr/bin/pipewire -c %h/.config/cassandra/eq.conf
Restart=on-failure
""", encoding="utf-8")
            _run(["systemctl", "--user", "daemon-reload"])

    def _start_eq(self, mac: str, sink: dict[str, Any]) -> None:
        with self._lock:
            self._write_conf(sink["name"])
            _run(["systemctl", "--user", "restart", EQ_SERVICE], timeout=20)
            node = None
            for _ in range(20):
                time.sleep(0.25)
                node = _node_by_name(EQ_NODE)
                if node:
                    break
            if not node:
                _run(["wpctl", "set-default", str(sink["id"])])
                raise RuntimeError("o equalizador não subiu; a caixa continua tocando sem ele")
            _run(["wpctl", "set-default", str(node["id"])])
            self._eq_mac = mac.upper()
            self._apply_gains(_eq_of(mac), node)
        self._ensure_watch()

    def _stop_eq(self, fallback: dict[str, Any] | None = None) -> None:
        with self._lock:
            if fallback:
                _run(["wpctl", "set-default", str(fallback["id"])])
            _run(["systemctl", "--user", "stop", EQ_SERVICE], timeout=20)
            self._eq_mac = None

    @staticmethod
    def _apply_gains(eq: dict[str, Any], node: dict[str, Any] | None = None) -> None:
        node = node or _node_by_name(EQ_NODE)
        if not node:
            return
        params = f'{{ params = [ "bass:Gain" {float(eq["bass"]):.1f} "treble:Gain" {float(eq["treble"]):.1f} ] }}'
        _run(["pw-cli", "set-param", str(node["id"]), "Props", params])

    # ── vigia: a caixa sumiu -> saída normal; voltou com o EQ ligado -> religa ──
    def _ensure_watch(self) -> None:
        if self._watch and self._watch.is_alive():
            return
        self._watch = threading.Thread(target=self._watch_loop, daemon=True, name="bt-eq-watch")
        self._watch.start()

    def _watch_loop(self) -> None:
        while True:
            time.sleep(10)
            try:
                self._tick()
            except Exception:  # noqa: BLE001 — o vigia nunca pode morrer
                pass

    def _tick(self) -> None:
        if self._eq_mac:
            sink = bt_sink(self._eq_mac)
            if sink and _eq_of(self._eq_mac)["enabled"] and not _node_by_name(EQ_NODE):
                # o filtro caiu (ex.: o WirePlumber reiniciou): religa, senão o som vai para a saída errada
                self._start_eq(self._eq_mac, sink)
                return
            if not sink:  # a caixa desconectou: o som volta para a saída normal
                self._stop_eq()
                builtin = next((n for n in _nodes() if n["props"].get("media.class") == "Audio/Sink"
                                and n["props"].get("node.name") != EQ_NODE), None)
                if builtin:
                    _run(["wpctl", "set-default", str(builtin["id"])])
            return
        for mac, eq in _load_eq().items():
            if eq.get("enabled"):
                sink = bt_sink(mac)
                if sink:
                    self._start_eq(mac, sink)
                    return

    def start(self) -> None:
        """Na inicialização: religa o equalizador de uma caixa já conectada e liga o vigia."""
        threading.Thread(target=self._boot, daemon=True, name="bt-eq-boot").start()

    def _boot(self) -> None:
        time.sleep(5)
        try:
            self._tick()
        except Exception:  # noqa: BLE001
            pass
        self._ensure_watch()


bt_audio = BtAudio()
