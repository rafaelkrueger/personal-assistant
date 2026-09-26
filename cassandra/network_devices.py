"""Aparelhos da mesma rede: descobrir (SSDP/UPnP, mDNS e portas de controle), conectar, classificar e controlar.

Nada aqui é "só TV": a descoberta mostra qualquer aparelho que se anuncia na rede (nome, fabricante, modelo).
Ao conectar, o aparelho é classificado pelo que ele mesmo anuncia (tipo UPnP, serviços mDNS, fabricante) —
TV, player de streaming, computador, roteador, caixa de som, lâmpada, casa inteligente, impressora... — e,
se existir um controle para ele (um "driver"), a UI mostra "Controlar" com a tela certa para a categoria
(TV e player de streaming: o controle remoto). Usado pela aba "Aparelhos", pela skill de voz/chat e pela API.

Controles (drivers) que existem hoje:
  firetv   Fire TV / Android TV com depuração pela rede (ADB, porta 5555). Controle completo; liga/desliga a TV pelo
           HDMI-CEC. Na 1ª conexão a TV pergunta "Permitir depuração?" — marque "sempre" e aceite.
  webos    LG webOS (porta 3000/3001). Na 1ª conexão a TV pede para aceitar a Cassandra.
  samsung  Samsung Tizen (2016+, porta 8001/8002). Na 1ª conexão a TV pede para permitir.
  roku     Roku / TVs Roku (ECP, porta 8060). Sem pareamento.
  dial     Qualquer aparelho que anuncia DIAL (ex.: TV Multilaser): abre e fecha apps (YouTube, Netflix...), mais nada.
Para uma categoria nova (ex.: lâmpadas), basta um driver novo em DRIVERS e a tela dela na UI.

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
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:40] or "aparelho"


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

_SSDP_TARGETS = ["ssdp:all", "upnp:rootdevice", "urn:dial-multiscreen-org:service:dial:1",
                 "urn:lge-com:service:webos-second-screen:1", "urn:samsung.com:device:RemoteControlReceiver:1",
                 "roku:ecp"]
# Portas que indicam um controle conhecido (checadas só nos aparelhos achados).
_CONTROL_PORTS = {5555: "firetv", 8060: "roku", 3000: "webos", 3001: "webos", 8002: "samsung", 8001: "samsung"}


def _own_ips() -> set[str]:
    ips = {"127.0.0.1"}
    try:
        out = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=3).stdout
        ips.update(out.split())
    except (OSError, subprocess.SubprocessError):
        pass
    return ips


def _entry(found: dict, host: str) -> dict[str, Any]:
    return found.setdefault(host, {"host": host, "ssdp": set(), "device_types": set(), "mdns": set(),
                                   "names": [], "manufacturer": "", "model": "", "dial_url": None,
                                   "hostname": "", "ports": set()})


def _ssdp(found: dict, timeout: float) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(0.5)
    for st in _SSDP_TARGETS:
        msg = f"M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 2\r\nST: {st}\r\n\r\n"
        try:
            sock.sendto(msg.encode(), ("239.255.255.250", 1900))
        except OSError:
            pass
    locations: dict[str, set[str]] = {}
    end = time.time() + timeout
    while time.time() < end:
        try:
            data, addr = sock.recvfrom(65507)
        except socket.timeout:
            continue
        except OSError:
            break
        text = data.decode(errors="replace")
        info = _entry(found, addr[0])
        m = re.search(r"(?im)^(?:st|nt):\s*(.+)$", text)
        if m:
            info["ssdp"].add(m.group(1).strip())
        m = re.search(r"(?im)^location:\s*(\S+)", text)
        if m:
            locations.setdefault(addr[0], set()).add(m.group(1).strip())
    sock.close()
    for host, locs in locations.items():
        info = found[host]
        for loc in locs:
            try:
                status, xml, headers = _http("GET", loc, timeout=3)
            except DeviceError:
                continue
            if status != 200:
                continue
            port = urllib.parse.urlparse(loc).port
            if port:
                info["ports"].add(port)
            info["dial_url"] = info["dial_url"] or next(
                (v for k, v in headers.items() if k.lower() == "application-url"), None)
            for tag, key in (("deviceType", "device_types"),):
                info[key].update(x.strip() for x in re.findall(rf"<{tag}>(.*?)</{tag}>", xml))
            m = re.search(r"<friendlyName>(.*?)</friendlyName>", xml)
            if m and m.group(1).strip():
                info["names"].insert(0, m.group(1).strip())
            for tag, key in (("manufacturer", "manufacturer"), ("modelName", "model")):
                m = re.search(rf"<{tag}>(.*?)</{tag}>", xml)
                if m and not info[key]:
                    info[key] = m.group(1).strip()


def _mdns(found: dict, timeout: float) -> None:
    """Todos os tipos de serviço anunciados por mDNS (nada fixo): _googlecast, _hap, _ipp, _spotify-connect..."""
    try:
        from zeroconf import ServiceBrowser, Zeroconf, ZeroconfServiceTypes
    except ImportError:
        return
    try:
        types = ZeroconfServiceTypes.find(timeout=min(3.0, timeout))
    except Exception:  # noqa: BLE001 — rede sem multicast etc.
        return
    zc = Zeroconf()

    class _Listener:
        def add_service(self, z, service_type, name):
            try:
                info = z.get_service_info(service_type, name, timeout=1500)
            except Exception:  # noqa: BLE001
                return
            if not info:
                return
            for addr in info.parsed_addresses():
                if ":" in addr:
                    continue
                entry = _entry(found, addr)
                entry["mdns"].add(service_type.replace(".local.", ""))
                instance = name.replace("." + service_type, "")
                if instance and not re.fullmatch(r"[0-9A-Fa-f]{12,}", instance) and ":" not in instance:
                    entry["names"].append(re.sub(r"\s*\[[0-9a-f:]{17}\]$", "", instance))
                if info.server and not entry["hostname"]:
                    entry["hostname"] = info.server.rstrip(".")
                if info.port:
                    entry["ports"].add(info.port)

        update_service = add_service

        def remove_service(self, *args):
            pass

    try:
        browsers = [ServiceBrowser(zc, t, _Listener()) for t in types]
        time.sleep(timeout)
        for b in browsers:
            b.cancel()
    finally:
        zc.close()


# Classificação: o que o próprio aparelho anuncia -> categoria. É a única "tabela"; a UI só mostra o resultado.
_CATEGORY_RULES: list[tuple[str, str]] = [
    ("router", r"internetgatewaydevice|wanconnectiondevice"),
    ("streaming", r"\baft[a-z]*\b|firetv|fire tv|chromecast|_googlecast|_amzn-wplay|roku (stick|express|streaming)"),
    ("tv", r"tvdevice|_androidtvremote|webos|samsung.*tv|remotecontrolreceiver|\btv\b|dial:1|mdx-netflix"),
    ("speaker", r"_spotify-connect|_raop|_sonos|zoneplayer|speaker|soundbar"),
    ("light", r"_hue|lightbulb|\blight|lamp|lampada|yeelight|_lifx|dimmablelight"),
    ("printer", r"_ipp|_printer|_pdl-datastream|printer"),
    ("computer", r"_workstation|_dosvc|_smb|_sftp|_ssh|_rdp|windows|macbook|desktop-"),
    ("smart_home", r"_hap|_matter|_homekit|_miio|tuya"),
    ("media_server", r"mediaserver|_daap|plex"),
]


def classify(info: dict[str, Any]) -> str:
    text = " ".join([*info.get("ssdp", []), *info.get("device_types", []), *info.get("mdns", []),
                     *info.get("names", []), info.get("manufacturer") or "", info.get("model") or "",
                     info.get("hostname") or ""]).lower()
    for category, pattern in _CATEGORY_RULES:
        if re.search(pattern, text):
            return category
    return "other"


def _control_for(info: dict[str, Any]) -> str | None:
    """O driver que controla este aparelho, pelo que ele anuncia e pelas portas abertas."""
    st = " ".join(info.get("ssdp", [])).lower()
    manufacturer = (info.get("manufacturer") or "").lower()
    if "webos" in st or "lge" in st:
        return "webos"
    if "samsung" in st or ("samsung" in manufacturer and "remotecontrol" in st):
        return "samsung"
    if "roku" in st or "roku" in manufacturer:
        return "roku"
    for port, driver in _CONTROL_PORTS.items():
        if driver in ("webos", "samsung") and not (info.get("ssdp") or info.get("device_types")):
            continue  # porta genérica demais sem nenhum anúncio que confirme
        if _port_open(info["host"], port):
            return driver
    if info.get("dial_url"):
        return "dial"
    return None


def discover(timeout: float = 4.0) -> list[dict[str, Any]]:
    """Todos os aparelhos que se anunciam na rede (menos o próprio Pi), com o que se sabe de cada um."""
    found: dict[str, dict[str, Any]] = {}
    mdns = threading.Thread(target=_mdns, args=(found, timeout), daemon=True)
    mdns.start()
    _ssdp(found, timeout)
    mdns.join(timeout + 4)
    own = _own_ips()
    out = []
    for host, info in list(found.items()):
        if host in own:
            continue
        names = [n for n in info["names"] if n]
        name = names[0] if names else (info["model"] or info["hostname"].split(".")[0] or host)
        if name.isupper() and name.isalpha() and len(name) > 3:
            name = name.title()  # "MULTILASER" -> "Multilaser"
        out.append({
            "host": host, "name": name, "manufacturer": info["manufacturer"], "model": info["model"],
            "hostname": info["hostname"], "dial_url": info["dial_url"],
            "category": classify(info), "control": _control_for(info),
            "services": sorted(info["mdns"] | {s for s in info["ssdp"] if not s.startswith("uuid:")})[:12],
            "ports": sorted(info["ports"])[:10],
        })
    return sorted(out, key=lambda d: [int(x) for x in d["host"].split(".")])


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
        port = int(self.device.get("adb_port") or 5555)
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
                self._conns.pop(f"{self.host}:{int(self.device.get('adb_port') or 5555)}", None)
                return self._conn().shell(cmd, timeout_s=10) or ""

    def pair(self) -> dict[str, Any]:
        with self._lock:
            self._conn(auth_timeout=40)  # tempo para aceitar "Permitir depuração?" na TV
        model = self._shell("getprop ro.product.model").strip()
        return {"model": model} if model else {}

    def online(self) -> bool:
        return _port_open(self.host, int(self.device.get("adb_port") or 5555))

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
CONTROL_LABELS = {"firetv": "Fire TV / Android TV (ADB)", "dial": "só abrir apps (DIAL)", "roku": "Roku",
                  "webos": "LG webOS", "samsung": "Samsung"}
# Categorias com tela de controle remoto de TV na UI (a UI escolhe a tela pela categoria).
TV_LIKE = {"tv", "streaming"}


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
        except (OSError, ValueError):
            return []
        devices = data if isinstance(data, list) else []
        for d in devices:  # formato antigo (só TVs): "kind" era o driver
            if "kind" in d and "control" not in d:
                d["control"] = d.pop("kind")
                d.setdefault("category", "streaming" if d["control"] == "firetv" else "tv")
                if "port" in d:
                    d["adb_port"] = d.pop("port")
        return devices

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

    def _controllable(self, category: set[str] | None = None) -> list[dict[str, Any]]:
        return [d for d in self._load() if d.get("control") and (category is None or d.get("category") in category)]

    def default(self) -> dict[str, Any] | None:
        """O aparelho dos comandos de voz sem nome ("desliga a TV"): o marcado como padrão, senão o 1º que
        tem controle de TV."""
        tvs = self._controllable(TV_LIKE)
        return next((d for d in tvs if d.get("default")), tvs[0] if tvs else None)

    def pick(self, text: str = "") -> dict[str, Any] | None:
        """O aparelho citado no pedido ("na TV da sala", "no fire tv"); sem citação, o padrão."""
        t = _slug(text).replace("-", " ")
        controllable = self._controllable()
        for d in controllable:
            name = _slug(d.get("name", "")).replace("-", " ")
            if name and name in t:
                return d
        if "fire" in t:
            fire = next((d for d in controllable if d["control"] == "firetv"), None)
            if fire:
                return fire
        return self.default()

    @staticmethod
    def public(device: dict[str, Any], check_online: bool = False) -> dict[str, Any]:
        control = device.get("control")
        driver = DRIVERS.get(control) if control else None
        view = {k: device.get(k) for k in ("id", "name", "host", "model", "manufacturer", "category", "control",
                                           "default")}
        view["control_label"] = CONTROL_LABELS.get(control or "", "")
        view["capabilities"] = sorted(driver.capabilities) if driver else []
        view["remote"] = "tv" if driver and device.get("category") in TV_LIKE else None  # qual tela de controle
        if check_online:
            try:
                if driver:
                    view["online"] = driver(device).online()
                else:
                    ports = device.get("ports") or [80]
                    view["online"] = any(_port_open(device["host"], int(p), 0.6) for p in ports[:3])
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
            # antes de conectar: só o que o aparelho anuncia (nome, fabricante, modelo) — a classificação vem ao conectar
            "found": [{k: f.get(k) for k in ("host", "name", "manufacturer", "model", "hostname")}
                      for f in self._found if f["host"] not in hosts],
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
            self._jobs[host] = {"state": "running", "message": _pair_hint(found.get("control")), "at": time.time()}
        threading.Thread(target=self._connect, args=(found,), daemon=True, name="device-pair").start()

    def _connect(self, found: dict[str, Any]) -> None:
        host = found["host"]
        device = {"id": _slug(found["name"]) + "-" + host.split(".")[-1], "name": found["name"], "host": host,
                  "category": found["category"], "control": found.get("control"),
                  "model": found.get("model"), "manufacturer": found.get("manufacturer"),
                  "hostname": found.get("hostname"), "dial_url": found.get("dial_url"),
                  "services": found.get("services"), "ports": found.get("ports"), "mac": _mac_of(host)}
        try:
            if device["control"]:
                device.update({k: v for k, v in DRIVERS[device["control"]](device).pair().items() if v})
        except Exception as exc:  # noqa: BLE001 — o erro vai para a UI
            with self._lock:
                self._jobs[host] = {"state": "error", "at": time.time(),
                                    "message": f"Não conectou em {found['name']}: {exc}"}
            return
        devices = [d for d in self._load() if d["host"] != host]
        if device["control"] and device["category"] in TV_LIKE:
            device["default"] = not any(d.get("default") for d in devices)
        devices.append(device)
        self._save(devices)
        label = CATEGORY_LABELS.get(device["category"], "aparelho")
        with self._lock:
            self._jobs[host] = {"state": "ok", "at": time.time(),
                                "message": f"{found['name']} conectado — identificado como {label.lower()}."
                                           + ("" if device["control"] else " (sem controle disponível ainda)")}

    def forget(self, device_id: str) -> None:
        devices = [d for d in self._load() if d["id"] != device_id]
        tvs = [d for d in devices if d.get("control") and d.get("category") in TV_LIKE]
        if tvs and not any(d.get("default") for d in tvs):
            tvs[0]["default"] = True
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

    def set_category(self, device_id: str, category: str) -> None:
        """Corrige a classificação (se o aparelho se anunciou de um jeito enganoso)."""
        if category not in CATEGORY_LABELS:
            raise DeviceError("categoria inválida")
        devices = self._load()
        for d in devices:
            if d["id"] == device_id:
                d["category"] = category
        self._save(devices)

    # controlar
    def _driver(self, device_id: str):
        device = self.get(device_id)
        if not device:
            raise DeviceError("aparelho não encontrado")
        if not device.get("control"):
            raise DeviceError(f"{device['name']} ainda não tem controle pela Cassandra")
        return device, DRIVERS[device["control"]](device)

    def apps(self, device_id: str) -> list[dict[str, str]]:
        return self._driver(device_id)[1].apps()

    def command(self, device_id: str, action: str, value: Any = None) -> str:
        device, driver = self._driver(device_id)
        if action not in driver.capabilities:
            if device["control"] == "dial":
                return driver.command(action, value)  # a mensagem explica o que dá para fazer
            raise DeviceError(f"{device['name']} não aceita esse comando")
        return driver.command(action, value)


CATEGORY_LABELS = {"tv": "TV", "streaming": "Player de streaming", "speaker": "Caixa de som", "light": "Lâmpada",
                   "computer": "Computador", "router": "Roteador", "printer": "Impressora",
                   "smart_home": "Casa inteligente", "media_server": "Servidor de mídia", "other": "Aparelho"}


def _pair_hint(kind: str | None) -> str:
    return {
        "firetv": "Olhe a TV: aceite \"Permitir depuração USB?\" (marque \"Sempre permitir\"). Até 40 s.",
        "webos": "Olhe a TV: aceite o pedido de conexão da Cassandra. Até 60 s.",
        "samsung": "Olhe a TV: escolha \"Permitir\" para a Cassandra. Até 40 s.",
    }.get(kind or "", "Conectando…")


manager = DeviceManager()
