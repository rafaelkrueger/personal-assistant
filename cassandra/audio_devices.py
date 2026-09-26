"""Volume, saída de áudio e aparelhos Bluetooth — usados pela interface web e pela skill de volume.

Volume/saída: wpctl (PipeWire/WirePlumber, o padrão do Raspberry Pi OS); sem ele, pactl ou amixer.
Bluetooth: bluetoothctl (BlueZ). Procurar e parear levam segundos (parear, até ~30 s), mais que o limite
de ~26 s do proxy do Netlify: por isso rodam em segundo plano e a interface acompanha por GET /api/bluetooth.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
from typing import Any

_MAC_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")
_DEVICE_LINE = re.compile(r"^Device ([0-9A-F:]{17}) (.*)$")


def _run(cmd: list[str], timeout: float = 10) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


# ── Volume e saída de áudio ───────────────────────────────────────────────────

def _backend() -> str | None:
    for cmd in ("wpctl", "pactl", "amixer"):
        if shutil.which(cmd):
            return cmd
    return None


def get_volume() -> dict[str, Any]:
    """{"available", "backend", "volume" (0-100), "muted"}."""
    backend = _backend()
    volume, muted = None, False
    if backend == "wpctl":
        _, out = _run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
        m = re.search(r"Volume:\s*([\d.]+)", out)
        if m:
            volume = round(float(m.group(1)) * 100)
        muted = "MUTED" in out
    elif backend == "pactl":
        _, out = _run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
        m = re.search(r"(\d+)%", out)
        volume = int(m.group(1)) if m else None
        _, out = _run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"])
        muted = "yes" in out.lower()
    elif backend == "amixer":
        _, out = _run(["amixer", "get", "Master"])
        m = re.search(r"\[(\d+)%\]", out)
        volume = int(m.group(1)) if m else None
        muted = "[off]" in out
    return {"available": volume is not None, "backend": backend, "volume": volume, "muted": muted}


def set_volume(pct: int) -> dict[str, Any]:
    pct = max(0, min(100, int(pct)))
    backend = _backend()
    if backend == "wpctl":
        _run(["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"{pct / 100:.2f}"])
    elif backend == "pactl":
        _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{pct}%"])
    elif backend == "amixer":
        _run(["amixer", "set", "Master", f"{pct}%"])
    return get_volume()


def change_volume(delta: int) -> dict[str, Any]:
    current = get_volume().get("volume")
    if current is None:
        return get_volume()
    return set_volume(current + int(delta))


def set_mute(muted: bool) -> dict[str, Any]:
    backend = _backend()
    if backend == "wpctl":
        _run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if muted else "0"])
    elif backend == "pactl":
        _run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if muted else "0"])
    elif backend == "amixer":
        _run(["amixer", "set", "Master", "mute" if muted else "unmute"])
    return get_volume()


def list_outputs() -> list[dict[str, Any]]:
    """Saídas de áudio (sinks) do PipeWire: [{"id", "name", "default"}]. Vazio sem wpctl."""
    if _backend() != "wpctl":
        return []
    _, out = _run(["wpctl", "status"])
    outputs, in_audio, in_sinks = [], False, False
    for line in out.splitlines():
        clean = line.replace("│", " ").replace("├─", "  ").replace("└─", "  ").rstrip()
        stripped = clean.strip()
        if stripped in ("Audio", "Video", "Settings"):
            in_audio, in_sinks = stripped == "Audio", False
            continue
        if not in_audio:
            continue
        if stripped.endswith(":"):
            in_sinks = stripped == "Sinks:"
            continue
        if in_sinks:
            m = re.match(r"^(\*)?\s*(\d+)\.\s+(.+?)(?:\s+\[vol:.*\])?$", stripped)
            if m:
                outputs.append({"id": int(m.group(2)), "name": m.group(3).strip(), "default": bool(m.group(1))})
    return outputs


def set_output(sink_id: int) -> bool:
    if not any(o["id"] == int(sink_id) for o in list_outputs()):
        return False
    code, _ = _run(["wpctl", "set-default", str(int(sink_id))])
    return code == 0


def audio_status() -> dict[str, Any]:
    return {**get_volume(), "outputs": list_outputs()}


# ── Bluetooth ─────────────────────────────────────────────────────────────────

def valid_mac(mac: str) -> str | None:
    mac = (mac or "").strip().upper()
    return mac if _MAC_RE.match(mac) else None


def _devices(filter_: str | None = None) -> dict[str, str]:
    cmd = ["bluetoothctl", "devices"] + ([filter_] if filter_ else [])
    _, out = _run(cmd)
    found = {}
    for line in out.splitlines():
        m = _DEVICE_LINE.match(line.strip())
        if m:
            found[m.group(1)] = m.group(2).strip()
    return found


def _looks_unnamed(mac: str, name: str) -> bool:
    return not name or name.replace("-", ":").upper() == mac


class BluetoothManager:
    """Uma operação demorada por vez (procurar, parear+conectar), em segundo plano."""

    SCAN_SECONDS = 20

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._job: dict[str, Any] | None = None  # {"action", "mac", "state": running|ok|error, "message", "at"}
        self._scan_proc: subprocess.Popen | None = None
        self._scan_until = 0.0

    @staticmethod
    def available() -> bool:
        return shutil.which("bluetoothctl") is not None

    # ── leitura ──
    def status(self) -> dict[str, Any]:
        if not self.available():
            return {"available": False, "powered": False, "scanning": False, "devices": [], "job": None}
        _, show = _run(["bluetoothctl", "show"])
        powered = "Powered: yes" in show
        known = _devices()
        paired = _devices("Paired")
        connected = _devices("Connected")
        trusted = _devices("Trusted")
        devices = []
        for mac, name in known.items():
            is_paired = mac in paired
            if not is_paired and _looks_unnamed(mac, name):
                continue  # aparelho sem nome achado na busca: só polui a lista
            devices.append({
                "mac": mac,
                "name": name if not _looks_unnamed(mac, name) else mac,
                "paired": is_paired,
                "connected": mac in connected,
                "trusted": mac in trusted,
            })
        devices.sort(key=lambda d: (not d["connected"], not d["paired"], d["name"].lower()))
        with self._lock:
            job = dict(self._job) if self._job else None
        return {"available": True, "powered": powered, "scanning": self.scanning(), "devices": devices, "job": job}

    def scanning(self) -> bool:
        return self._scan_proc is not None and self._scan_proc.poll() is None

    # ── operações ──
    def _set_job(self, action: str, mac: str | None, state: str, message: str) -> None:
        with self._lock:
            self._job = {"action": action, "mac": mac, "state": state, "message": message, "at": time.time()}

    def _busy(self) -> bool:
        with self._lock:
            return bool(self._job and self._job["state"] == "running")

    def set_power(self, on: bool) -> bool:
        code, out = _run(["bluetoothctl", "power", "on" if on else "off"])
        return code == 0 and "succeeded" in out.lower()

    def start_scan(self, seconds: int | None = None) -> bool:
        """Procura aparelhos novos por alguns segundos (o aparelho precisa estar em modo de pareamento)."""
        if self.scanning() or self._busy():
            return False
        self.set_power(True)
        seconds = max(5, min(60, int(seconds or self.SCAN_SECONDS)))
        self._scan_proc = subprocess.Popen(
            ["bluetoothctl", "--timeout", str(seconds), "scan", "on"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._scan_until = time.time() + seconds
        return True

    def stop_scan(self) -> None:
        proc = self._scan_proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        _run(["bluetoothctl", "scan", "off"], timeout=5)

    def start_connect(self, mac: str) -> bool:
        """Pareia (se preciso), confia e conecta — em segundo plano."""
        if self._busy():
            return False
        self._set_job("connect", mac, "running", "Conectando…")
        threading.Thread(target=self._connect, args=(mac,), daemon=True, name="bt-connect").start()
        return True

    def _connect(self, mac: str) -> None:
        try:
            if self.scanning():
                self.stop_scan()  # a busca atrapalha o pareamento
            name = _devices().get(mac, mac)
            if mac not in _devices("Paired"):
                self._set_job("connect", mac, "running", f"Pareando com {name}…")
                # Caixas de som e fones não pedem PIN: o agente NoInputNoOutput aceita sozinho.
                code, out = _run(["bluetoothctl", "--agent", "NoInputNoOutput", "--timeout", "30", "pair", mac],
                                 timeout=40)
                if "Pairing successful" not in out and "AlreadyExists" not in out:
                    reason = _last_meaningful_line(out) or "sem resposta do aparelho"
                    self._set_job("connect", mac, "error",
                                  f"Não pareou com {name} ({reason}). Deixe o aparelho em modo de pareamento e tente de novo.")
                    return
            _run(["bluetoothctl", "trust", mac])  # reconecta sozinho depois de um reboot
            self._set_job("connect", mac, "running", f"Conectando em {name}…")
            # A 1ª tentativa às vezes falha (le-connection-abort-by-local: a BlueZ tenta LE antes do clássico);
            # a seguinte costuma conectar.
            for attempt in range(3):
                code, out = _run(["bluetoothctl", "--timeout", "20", "connect", mac], timeout=30)
                if "Connection successful" in out or mac in _devices("Connected"):
                    break
                if attempt == 2:
                    break
                self._set_job("connect", mac, "running", f"Conectando em {name}… (tentativa {attempt + 2})")
                time.sleep(2)
            if "Connection successful" in out or mac in _devices("Connected"):
                self._set_job("connect", mac, "ok", f"{name} conectado.")
            else:
                reason = _last_meaningful_line(out) or "sem resposta do aparelho"
                self._set_job("connect", mac, "error", f"Não conectou em {name} ({reason}). Ele está ligado e por perto?")
        except Exception as exc:  # noqa: BLE001 — o erro vai para a interface
            self._set_job("connect", mac, "error", f"Erro: {exc}")

    def disconnect(self, mac: str) -> bool:
        code, out = _run(["bluetoothctl", "disconnect", mac], timeout=15)
        ok = "Successful disconnected" in out or mac not in _devices("Connected")
        name = _devices().get(mac, mac)
        self._set_job("disconnect", mac, "ok" if ok else "error",
                      f"{name} desconectado." if ok else f"Não desconectou {name}.")
        return ok

    def forget(self, mac: str) -> bool:
        name = _devices().get(mac, mac)
        code, out = _run(["bluetoothctl", "remove", mac], timeout=15)
        ok = "Device has been removed" in out or mac not in _devices()
        self._set_job("forget", mac, "ok" if ok else "error",
                      f"{name} esquecido." if ok else f"Não consegui esquecer {name}.")
        return ok


def _last_meaningful_line(out: str) -> str:
    for line in reversed(out.strip().splitlines()):
        line = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
        if line and not line.startswith(("Agent registered", "Agent unregistered", "[")):
            return line[:120]
    return ""


bluetooth = BluetoothManager()
