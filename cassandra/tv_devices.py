"""TVs e players na mesma rede: descobrir, conectar (parear) e controlar — ligar/desligar, volume, apps (Netflix,
YouTube...), HDMI, setas/OK/voltar/início, play/pause. Usado pela aba "Aparelhos" da UI e pela skill de TV (voz/chat).

Tipos suportados (cada um com o próprio "driver"):
  firetv   Fire TV / Android TV com depuração pela rede (ADB, porta 5555). Controle completo; liga/desliga a TV pelo
           HDMI-CEC. Na 1ª conexão a TV pergunta "Permitir depuração?" — marque "sempre" e aceite.
  webos    LG webOS (porta 3000/3001). Na 1ª conexão a TV pede para aceitar a Cassandra.
  samsung  Samsung Tizen (2016+, porta 8001/8002). Na 1ª conexão a TV pede para permitir.
  roku     Roku / TVs Roku (ECP, porta 8060). Sem pareamento.
  dial     Qualquer TV que só anuncia DIAL (ex.: Multilaser): abre e fecha apps (YouTube, Netflix...), mais nada.
Ligar uma TV desligada: firetv (CEC) e roku ligam; webos/samsung usam Wake-on-LAN (precisa estar ativado na TV).

Os aparelhos conectados ficam em data/devices.json (com a chave de pareamento de cada um — fora do git).
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DEVICES_FILE = Path("data/devices.json")
ADB_KEY = Path("data/adbkey")

# Apps conhecidos: nome falado -> id em cada sistema.
APPS: dict[str, dict[str, str]] = {
    "netflix": {"label": "Netflix", "firetv": "com.netflix.ninja", "webos": "netflix", "roku": "12",
                "samsung": "3201907018807", "dial": "Netflix"},
    "youtube": {"label": "YouTube", "firetv": "com.amazon.firetv.youtube", "webos": "youtube.leanback.v4",
                "roku": "837", "samsung": "111299001912", "dial": "YouTube"},
    "prime": {"label": "Prime Video", "firetv": "com.amazon.avod", "webos": "amazon", "roku": "13",
              "samsung": "3201910019365", "dial": "AmazonInstantVideo"},
    "disney": {"label": "Disney+", "firetv": "com.disney.disneyplus", "webos": "com.disney.disneyplus-prod",
               "roku": "291097", "samsung": "3201901017640"},
    "globoplay": {"label": "Globoplay", "firetv": "com.globo.globotv", "webos": "globoplay",
                  "samsung": "3201908019041"},
    "max": {"label": "Max", "firetv": "com.wbd.stream", "webos": "com.hbo.hbomax", "samsung": "3201601007230"},
    "spotify": {"label": "Spotify", "firetv": "com.spotify.tv.android", "webos": "spotify-beehive",
                "roku": "22297", "samsung": "3201606009684"},
    "twitch": {"label": "Twitch", "firetv": "tv.twitch.android.viewer", "webos": "twitch"},
}

# Ações de controle remoto que a UI e a skill conhecem.
REMOTE_KEYS = ["up", "down", "left", "right", "ok", "back", "home", "menu", "play_pause", "rewind", "forward"]
ACTIONS = ["power_on", "power_off", "volume_up", "volume_down", "mute", "channel_up", "channel_down",
           *REMOTE_KEYS, "input", "app", "close_app"]


class DeviceError(Exception):
    pass


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:40] or "tv"


def _http(method: str, url: str, body: bytes | None = None, timeout: float = 5,
          headers: dict | None = None) -> tuple[int, str, dict]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode(errors="replace"), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace"), dict(exc.headers or {})
    except (urllib.error.URLError, OSError) as exc:
        raise DeviceError(f"sem resposta ({exc})") from exc


def _port_open(host: str, port: int, timeout: float = 0.8) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _mac_of(host: str) -> str | None:
    """MAC do aparelho pela tabela ARP (para ligar por Wake-on-LAN)."""
    try:
        out = subprocess.run(["ip", "neigh", "show", host], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"lladdr ([0-9a-f:]{17})", out)
    return m.group(1) if m else None


def _wake_on_lan(mac: str) -> None:
    raw = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    packet = b"\xff" * 6 + raw * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for port in (9, 7):
            s.sendto(packet, ("255.255.255.255", port))


# ── Descoberta ────────────────────────────────────────────────────────────────

_SSDP_TARGETS = ["ssdp:all", "urn:dial-multiscreen-org:service:dial:1", "urn:lge-com:service:webos-second-screen:1",
                 "urn:samsung.com:device:RemoteControlReceiver:1", "roku:ecp"]


def discover(timeout: float = 4.0) -> list[dict[str, Any]]:
    """TVs e players que se anunciam na rede (SSDP/DIAL), com o tipo de controle que cada um aceita."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(0.5)
    for st in _SSDP_TARGETS:
        msg = f"M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 2\r\nST: {st}\r\n\r\n"
        try:
            sock.sendto(msg.encode(), ("239.255.255.250", 1900))
        except OSError:
            pass
    seen: dict[str, dict[str, Any]] = {}
    end = time.time() + timeout
    while time.time() < end:
        try:
            data, addr = sock.recvfrom(65507)
        except socket.timeout:
            continue
        except OSError:
            break
        text = data.decode(errors="replace")
        info = seen.setdefault(addr[0], {"host": addr[0], "st": set(), "locations": set(), "server": ""})
        for key, target in (("st", r"(?im)^(?:st|nt):\s*(.+)$"), ("locations", r"(?im)^location:\s*(\S+)")):
            m = re.search(target, text)
            if m:
                info[key].add(m.group(1).strip())
        m = re.search(r"(?im)^server:\s*(.+)$", text)
        if m:
            info["server"] = m.group(1).strip()
    sock.close()

    found = []
    for host, info in seen.items():
        st = " ".join(info["st"]).lower()
        name = manufacturer = model = ""
        dial_url = None
        for loc in info["locations"]:
            try:
                status, xml, headers = _http("GET", loc, timeout=3)
            except DeviceError:
                continue
            if status != 200:
                continue
            dial_url = dial_url or next((v for k, v in headers.items() if k.lower() == "application-url"), None)
            for tag in ("friendlyName", "manufacturer", "modelName"):
                m = re.search(rf"<{tag}>(.*?)</{tag}>", xml)
                if m and not {"friendlyName": name, "manufacturer": manufacturer, "modelName": model}[tag]:
                    value = m.group(1).strip()
                    if tag == "friendlyName":
                        name = value
                    elif tag == "manufacturer":
                        manufacturer = value
                    else:
                        model = value
        if "internetgatewaydevice" in st and not dial_url:
            continue  # o roteador
        kind = None
        if "webos" in st or "lge" in st:
            kind = "webos"
        elif "samsung" in st or "samsung" in manufacturer.lower():
            kind = "samsung"
        elif "roku" in st or "roku" in manufacturer.lower():
            kind = "roku"
        elif _port_open(host, 5555):
            kind = "firetv"  # ADB pela rede (Fire TV, Android TV com depuração ligada)
        elif dial_url or "dial" in st:
            kind = "dial"
        if not kind:
            continue
        found.append({
            "host": host, "kind": kind, "name": name or model or host,
            "manufacturer": manufacturer, "model": model, "dial_url": dial_url,
        })
    return sorted(found, key=lambda d: d["host"])


# ── Drivers ───────────────────────────────────────────────────────────────────

class _Driver:
    kind = ""
    capabilities: set[str] = set()

    def __init__(self, device: dict[str, Any]) -> None:
        self.device = device
        self.host = device["host"]

    def pair(self) -> dict[str, Any]:
        """Conecta pela 1ª vez (a TV pode pedir confirmação na tela). Devolve dados a guardar (chaves etc.)."""
        return {}

    def online(self) -> bool:
        return True

    def apps(self) -> list[dict[str, str]]:
        return [{"id": key, "label": app["label"]} for key, app in APPS.items() if self.kind in app]

    def command(self, action: str, value: Any = None) -> str:
        raise DeviceError("não suportado nesta TV")

    def _app_id(self, value: Any) -> tuple[str, str]:
        key = find_app(str(value or ""))
        if not key or self.kind not in APPS.get(key, {}):
            raise DeviceError(f"não sei abrir {value!r} nesta TV")
        return APPS[key][self.kind], APPS[key]["label"]


class FireTvDriver(_Driver):
    """ADB pela rede (adb-shell, sem o binário adb). Fire TV e Android TV com depuração ligada."""
    kind = "firetv"
    capabilities = {"power_on", "power_off", "volume_up", "volume_down", "mute", "app", "close_app",
                    *REMOTE_KEYS}
    KEYS = {"power_on": 224, "power_off": 223, "volume_up": 24, "volume_down": 25, "mute": 164,
            "up": 19, "down": 20, "left": 21, "right": 22, "ok": 23, "back": 4, "home": 3, "menu": 82,
            "play_pause": 85, "rewind": 89, "forward": 90, "channel_up": 166, "channel_down": 167}
    _lock = threading.Lock()
    _conns: dict[str, Any] = {}

    @staticmethod
    def _signer():
        from adb_shell.auth.keygen import keygen
        from adb_shell.auth.sign_pythonrsa import PythonRSASigner
        if not ADB_KEY.exists():
            ADB_KEY.parent.mkdir(parents=True, exist_ok=True)
            keygen(str(ADB_KEY))
            os.chmod(ADB_KEY, 0o600)
        return PythonRSASigner(Path(f"{ADB_KEY}.pub").read_text(), ADB_KEY.read_text())

    def _conn(self, auth_timeout: float = 3):
        from adb_shell.adb_device import AdbDeviceTcp
        port = int(self.device.get("port") or 5555)
        key = f"{self.host}:{port}"
        conn = self._conns.get(key)
        if conn is not None and conn.available:
            return conn
        conn = AdbDeviceTcp(self.host, port, default_transport_timeout_s=8)
        try:
            conn.connect(rsa_keys=[self._signer()], auth_timeout_s=auth_timeout)
        except Exception as exc:  # noqa: BLE001 — a lib levanta vários tipos
            raise DeviceError(f"não conectou ({type(exc).__name__}: {exc})") from exc
        self._conns[key] = conn
        return conn

    def _shell(self, cmd: str) -> str:
        with self._lock:
            try:
                return self._conn().shell(cmd, timeout_s=10) or ""
            except DeviceError:
                raise
            except Exception:  # conexão caiu: reconecta uma vez
                self._conns.pop(f"{self.host}:{int(self.device.get('port') or 5555)}", None)
                return self._conn().shell(cmd, timeout_s=10) or ""

    def pair(self) -> dict[str, Any]:
        with self._lock:
            self._conn(auth_timeout=40)  # tempo para aceitar "Permitir depuração?" na TV
        model = self._shell("getprop ro.product.model").strip()
        return {"model": model} if model else {}

    def online(self) -> bool:
        return _port_open(self.host, int(self.device.get("port") or 5555))

    def apps(self) -> list[dict[str, str]]:
        try:
            installed = set(re.findall(r"package:(\S+)", self._shell("pm list packages")))
        except DeviceError:
            installed = set()
        known = [{"id": key, "label": app["label"]} for key, app in APPS.items()
                 if app.get("firetv") and (not installed or app["firetv"] in installed)]
        return known

    def command(self, action: str, value: Any = None) -> str:
        if action in self.KEYS:
            self._shell(f"input keyevent {self.KEYS[action]}")
            return "ok"
        if action == "app":
            package, label = self._app_id(value)
            self._shell(f"monkey -p {package} -c android.intent.category.LAUNCHER 1")
            return f"Abrindo {label}"
        if action == "close_app":
            self._shell("input keyevent 3")
            return "ok"
        raise DeviceError("não suportado nesta TV")


class DialDriver(_Driver):
    """Só DIAL: abrir/fechar apps. Serve para TVs com sistema próprio (ex.: Multilaser)."""
    kind = "dial"
    capabilities = {"app", "close_app"}
    _running: dict[str, str] = {}

    def _base(self) -> str:
        url = self.device.get("dial_url")
        if not url:
            raise DeviceError("a TV não informou o endereço DIAL")
        return url if url.endswith("/") else url + "/"

    def online(self) -> bool:
        try:
            status, _, _ = _http("GET", self._base() + "YouTube", timeout=3)
            return status in (200, 404)
        except DeviceError:
            return False

    def apps(self) -> list[dict[str, str]]:
        out = []
        for key, app in APPS.items():
            name = app.get("dial")
            if not name:
                continue
            try:
                status, _, _ = _http("GET", self._base() + name, timeout=3)
            except DeviceError:
                break
            if status == 200:
                out.append({"id": key, "label": app["label"]})
        return out

    def command(self, action: str, value: Any = None) -> str:
        if action == "app":
            name, label = self._app_id(value)
            status, _, headers = _http("POST", self._base() + name, body=b"", timeout=10,
                                       headers={"Content-Type": "text/plain; charset=utf-8"})
            if status not in (200, 201):
                raise DeviceError(f"a TV recusou abrir {label} ({status})")
            location = next((v for k, v in headers.items() if k.lower() == "location"), None)
            if location:
                self._running[self.host] = location
            return f"Abrindo {label}"
        if action == "close_app":
            location = self._running.pop(self.host, None)
            if not location:
                raise DeviceError("não sei qual app está aberto")
            _http("DELETE", location, timeout=5)
            return "ok"
        raise DeviceError("esta TV só aceita abrir apps pela rede (para ligar/desligar e volume, use o controle "
                          "remoto, um Fire TV conectado nela ou um emissor infravermelho)")


class RokuDriver(_Driver):
    kind = "roku"
    capabilities = {"power_on", "power_off", "volume_up", "volume_down", "mute", "channel_up", "channel_down",
                    "input", "app", *REMOTE_KEYS}
    KEYS = {"power_on": "PowerOn", "power_off": "PowerOff", "volume_up": "VolumeUp", "volume_down": "VolumeDown",
            "mute": "VolumeMute", "up": "Up", "down": "Down", "left": "Left", "right": "Right", "ok": "Select",
            "back": "Back", "home": "Home", "menu": "Info", "play_pause": "Play", "rewind": "Rev", "forward": "Fwd",
            "channel_up": "ChannelUp", "channel_down": "ChannelDown"}

    def _url(self, path: str) -> str:
        return f"http://{self.host}:8060/{path}"

    def online(self) -> bool:
        return _port_open(self.host, 8060)

    def command(self, action: str, value: Any = None) -> str:
        if action in self.KEYS:
            _http("POST", self._url(f"keypress/{self.KEYS[action]}"), body=b"")
            return "ok"
        if action == "input":
            _http("POST", self._url(f"keypress/InputHDMI{int(value or 1)}"), body=b"")
            return f"HDMI {int(value or 1)}"
        if action == "app":
            app_id, label = self._app_id(value)
            _http("POST", self._url(f"launch/{app_id}"), body=b"")
            return f"Abrindo {label}"
        raise DeviceError("não suportado nesta TV")


class WebOsDriver(_Driver):
    kind = "webos"
    capabilities = {"power_on", "power_off", "volume_up", "volume_down", "mute", "channel_up", "channel_down",
                    "input", "app", "close_app", *REMOTE_KEYS}

    def _client(self, pairing: bool = False):
        from pywebostv.connection import WebOSClient
        client = WebOSClient(self.host, secure=True)
        try:
            client.connect()
        except Exception:  # noqa: BLE001 — TVs antigas: porta 3000 sem TLS
            client = WebOSClient(self.host)
            client.connect()
        store = {"client_key": self.device["client_key"]} if self.device.get("client_key") else {}
        for status in client.register(store, timeout=60 if pairing else 10):
            if status == WebOSClient.PROMPTED and not pairing:
                raise DeviceError("a TV pediu autorização de novo — conecte outra vez pela aba Aparelhos")
        return client, store.get("client_key")

    def pair(self) -> dict[str, Any]:
        _, key = self._client(pairing=True)
        return {"client_key": key, "mac": self.device.get("mac") or _mac_of(self.host)}

    def online(self) -> bool:
        return _port_open(self.host, 3000) or _port_open(self.host, 3001)

    def command(self, action: str, value: Any = None) -> str:
        if action == "power_on":
            mac = self.device.get("mac") or _mac_of(self.host)
            if not mac:
                raise DeviceError("sem o MAC da TV para ligar por Wake-on-LAN")
            _wake_on_lan(mac)
            return "ok"
        from pywebostv.controls import (ApplicationControl, InputControl, MediaControl, SourceControl,
                                        SystemControl, TvControl)
        client, _ = self._client()
        media = MediaControl(client)
        simple = {"power_off": lambda: SystemControl(client).power_off(), "volume_up": media.volume_up,
                  "volume_down": media.volume_down, "play_pause": media.play,
                  "channel_up": lambda: TvControl(client).channel_up(),
                  "channel_down": lambda: TvControl(client).channel_down()}
        if action in simple:
            simple[action]()
            return "ok"
        if action == "mute":
            media.mute(not media.get_mute())
            return "ok"
        if action == "app":
            app_id, label = self._app_id(value)
            apps = ApplicationControl(client)
            target = next((a for a in apps.list_apps() if a["id"] == app_id), None)
            if target is None:
                raise DeviceError(f"{label} não está instalado na TV")
            apps.launch(target)
            return f"Abrindo {label}"
        if action == "input":
            sources = SourceControl(client)
            wanted = f"HDMI_{int(value or 1)}"
            source = next((s for s in sources.list_sources() if s["id"].upper() == wanted), None)
            if source is None:
                raise DeviceError(f"a TV não tem {wanted.replace('_', ' ')}")
            sources.set_source(source)
            return f"HDMI {int(value or 1)}"
        if action in REMOTE_KEYS or action == "close_app":
            inp = InputControl(client)
            inp.connect_input()
            try:
                button = {"up": inp.up, "down": inp.down, "left": inp.left, "right": inp.right, "ok": inp.ok,
                          "back": inp.back, "home": inp.home, "menu": inp.menu, "close_app": inp.home,
                          "rewind": inp.back, "forward": inp.ok}.get(action)
                if button is None:
                    raise DeviceError("não suportado nesta TV")
                button()
            finally:
                inp.disconnect_input()
            return "ok"
        raise DeviceError("não suportado nesta TV")


class SamsungDriver(_Driver):
    kind = "samsung"
    capabilities = {"power_on", "power_off", "volume_up", "volume_down", "mute", "channel_up", "channel_down",
                    "input", "app", *REMOTE_KEYS}
    KEYS = {"power_off": "KEY_POWER", "volume_up": "KEY_VOLUP", "volume_down": "KEY_VOLDOWN", "mute": "KEY_MUTE",
            "up": "KEY_UP", "down": "KEY_DOWN", "left": "KEY_LEFT", "right": "KEY_RIGHT", "ok": "KEY_ENTER",
            "back": "KEY_RETURN", "home": "KEY_HOME", "menu": "KEY_MENU", "play_pause": "KEY_PLAY",
            "rewind": "KEY_REWIND", "forward": "KEY_FF", "channel_up": "KEY_CHUP", "channel_down": "KEY_CHDOWN"}

    def _tv(self, timeout: float = 8):
        from samsungtvws import SamsungTVWS
        return SamsungTVWS(host=self.host, port=8002, token=self.device.get("token"), timeout=timeout,
                           name="Cassandra")

    def pair(self) -> dict[str, Any]:
        tv = self._tv(timeout=40)  # tempo para "Permitir" na TV
        tv.open()
        token = tv.token
        tv.close()
        return {"token": token, "mac": self.device.get("mac") or _mac_of(self.host)}

    def online(self) -> bool:
        return _port_open(self.host, 8002) or _port_open(self.host, 8001)

    def command(self, action: str, value: Any = None) -> str:
        if action == "power_on":
            mac = self.device.get("mac") or _mac_of(self.host)
            if not mac:
                raise DeviceError("sem o MAC da TV para ligar por Wake-on-LAN")
            _wake_on_lan(mac)
            return "ok"
        tv = self._tv()
        if action in self.KEYS:
            tv.send_key(self.KEYS[action])
            return "ok"
        if action == "input":
            tv.send_key(f"KEY_HDMI{int(value or 1)}")
            return f"HDMI {int(value or 1)}"
        if action == "app":
            app_id, label = self._app_id(value)
            tv.run_app(app_id)
            return f"Abrindo {label}"
        raise DeviceError("não suportado nesta TV")


DRIVERS = {d.kind: d for d in (FireTvDriver, DialDriver, RokuDriver, WebOsDriver, SamsungDriver)}
KIND_LABELS = {"firetv": "Fire TV / Android TV", "dial": "Smart TV (só apps)", "roku": "Roku",
               "webos": "LG webOS", "samsung": "Samsung"}


def find_app(text: str) -> str | None:
    """'netflix', 'o youtube', 'prime video' -> chave em APPS."""
    t = _slug(text).replace("-", " ")
    aliases = {"prime": ["prime", "amazon"], "disney": ["disney"], "globoplay": ["globo"], "max": ["hbo", "max"]}
    for key in APPS:
        if key in t or any(a in t for a in aliases.get(key, [])):
            return key
    return None


# ── Aparelhos conectados ──────────────────────────────────────────────────────

class DeviceManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}  # host -> {"state", "message", "at"}
        self._found: list[dict[str, Any]] = []
        self._scanning = False

    # persistência
    def _load(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(DEVICES_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def _save(self, devices: list[dict[str, Any]]) -> None:
        DEVICES_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = DEVICES_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(devices, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, DEVICES_FILE)
        try:
            os.chmod(DEVICES_FILE, 0o600)
        except OSError:
            pass

    def devices(self) -> list[dict[str, Any]]:
        return self._load()

    def get(self, device_id: str) -> dict[str, Any] | None:
        return next((d for d in self._load() if d["id"] == device_id), None)

    def default(self) -> dict[str, Any] | None:
        """A TV "padrão" para comandos de voz: a marcada como padrão, senão a 1ª conectada."""
        devices = self._load()
        return next((d for d in devices if d.get("default")), devices[0] if devices else None)

    def pick(self, text: str = "") -> dict[str, Any] | None:
        """O aparelho citado no pedido ("na TV da sala", "no fire tv"); sem citação, o padrão."""
        t = _slug(text).replace("-", " ")
        for d in self._load():
            name = _slug(d.get("name", "")).replace("-", " ")
            if name and name in t:
                return d
        if "fire" in t:
            fire = next((d for d in self._load() if d["kind"] == "firetv"), None)
            if fire:
                return fire
        return self.default()

    @staticmethod
    def public(device: dict[str, Any], check_online: bool = False) -> dict[str, Any]:
        driver = DRIVERS[device["kind"]]
        view = {k: device.get(k) for k in ("id", "name", "kind", "host", "model", "manufacturer", "default")}
        view["kind_label"] = KIND_LABELS.get(device["kind"], device["kind"])
        view["capabilities"] = sorted(driver.capabilities)
        if check_online:
            try:
                view["online"] = driver(device).online()
            except Exception:  # noqa: BLE001
                view["online"] = False
        return view

    def status(self) -> dict[str, Any]:
        with self._lock:
            jobs = {k: dict(v) for k, v in self._jobs.items()}
        saved = self._load()
        hosts = {d["host"] for d in saved}
        return {
            "devices": [self.public(d, check_online=True) for d in saved],
            "found": [{**f, "kind_label": KIND_LABELS.get(f["kind"], f["kind"])} for f in self._found
                      if f["host"] not in hosts],
            "scanning": self._scanning,
            "jobs": jobs,
        }

    # descobrir / conectar / esquecer
    def scan(self) -> list[dict[str, Any]]:
        self._scanning = True
        try:
            self._found = discover()
        finally:
            self._scanning = False
        return self._found

    def start_connect(self, host: str) -> None:
        found = next((f for f in self._found if f["host"] == host), None)
        if found is None:
            raise DeviceError("procure os aparelhos de novo antes de conectar")
        with self._lock:
            if self._jobs.get(host, {}).get("state") == "running":
                return
            self._jobs[host] = {"state": "running", "message": _pair_hint(found["kind"]), "at": time.time()}
        threading.Thread(target=self._connect, args=(found,), daemon=True, name="tv-pair").start()

    def _connect(self, found: dict[str, Any]) -> None:
        host = found["host"]
        device = {"id": _slug(found["name"]) + "-" + host.split(".")[-1], "name": found["name"],
                  "kind": found["kind"], "host": host, "model": found.get("model"),
                  "manufacturer": found.get("manufacturer"), "dial_url": found.get("dial_url"),
                  "mac": _mac_of(host)}
        try:
            device.update({k: v for k, v in DRIVERS[device["kind"]](device).pair().items() if v})
        except Exception as exc:  # noqa: BLE001 — o erro vai para a UI
            with self._lock:
                self._jobs[host] = {"state": "error", "at": time.time(),
                                    "message": f"Não conectou em {found['name']}: {exc}"}
            return
        devices = [d for d in self._load() if d["host"] != host]
        device["default"] = not any(d.get("default") for d in devices)
        devices.append(device)
        self._save(devices)
        with self._lock:
            self._jobs[host] = {"state": "ok", "message": f"{found['name']} conectada.", "at": time.time()}

    def forget(self, device_id: str) -> None:
        devices = [d for d in self._load() if d["id"] != device_id]
        if devices and not any(d.get("default") for d in devices):
            devices[0]["default"] = True
        self._save(devices)

    def rename(self, device_id: str, name: str) -> None:
        devices = self._load()
        for d in devices:
            if d["id"] == device_id:
                d["name"] = name.strip()[:40] or d["name"]
        self._save(devices)

    def set_default(self, device_id: str) -> None:
        devices = self._load()
        for d in devices:
            d["default"] = d["id"] == device_id
        self._save(devices)

    # controlar
    def apps(self, device_id: str) -> list[dict[str, str]]:
        device = self.get(device_id)
        if not device:
            raise DeviceError("aparelho não encontrado")
        return DRIVERS[device["kind"]](device).apps()

    def command(self, device_id: str, action: str, value: Any = None) -> str:
        device = self.get(device_id)
        if not device:
            raise DeviceError("aparelho não encontrado")
        driver = DRIVERS[device["kind"]](device)
        if action not in driver.capabilities:
            if device["kind"] == "dial":
                return driver.command(action, value)  # a mensagem explica o que dá para fazer
            raise DeviceError(f"{device['name']} não aceita esse comando")
        return driver.command(action, value)


def _pair_hint(kind: str) -> str:
    return {
        "firetv": "Olhe a TV: aceite \"Permitir depuração USB?\" (marque \"Sempre permitir\"). Até 40 s.",
        "webos": "Olhe a TV: aceite o pedido de conexão da Cassandra. Até 60 s.",
        "samsung": "Olhe a TV: escolha \"Permitir\" para a Cassandra. Até 40 s.",
    }.get(kind, "Conectando…")


manager = DeviceManager()
