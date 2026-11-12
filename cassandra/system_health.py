"""Saúde do aparelho que roda a Cassandra (o Raspberry Pi): CPU, memória, swap, disco, temperatura, fonte e os
serviços da casa. Tudo lido do próprio Linux (/proc, /sys, vcgencmd, systemctl --user), sem dependências.

`snapshot()` devolve os números, um veredito geral (`ok | warn | bad`) e os motivos em português. Em outro sistema
(o PC com Windows, por exemplo) devolve `available: false`.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

# Serviços que importam para a casa (systemd --user no Pi): nome do serviço -> como aparece na tela.
SERVICES = [
    ("cassandra-assistant", "Cassandra"),
    ("cassandra-tunnel", "Túnel público"),
    ("cassandra-netlify-sync", "Site (Netlify) e vigia"),
    ("cassandra-spotify", "Spotify Connect"),
    ("pulse-health", "Pulse (saúde)"),
    ("cifra-finance", "Cifra (finanças)"),
    ("torque-car", "Torque (carro)"),
    ("lume-learning", "Lume (estudos)"),
]

# vcgencmd get_throttled: bits "agora" (0-3) e "desde que ligou" (16-19)
THROTTLE_BITS = {
    0: "Subtensão agora: a fonte não está dando conta",
    1: "CPU com frequência limitada agora",
    2: "CPU sendo freada agora (throttling)",
    3: "Limite de temperatura atingido: CPU reduzida para esfriar",
    16: "Teve subtensão desde que ligou (fonte fraca)",
    17: "Teve frequência limitada desde que ligou",
    18: "Teve throttling desde que ligou",
    19: "Bateu no limite de temperatura desde que ligou",
}

_last_cpu: tuple[float, int, int] | None = None   # (quando, ocioso, total) da última leitura de /proc/stat


def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _run(args: list[str], timeout: float = 3) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def parse_meminfo(text: str) -> dict[str, int]:
    """/proc/meminfo -> {campo: bytes}."""
    out: dict[str, int] = {}
    for line in text.splitlines():
        name, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            out[name.strip()] = int(parts[0]) * (1024 if len(parts) > 1 and parts[1] == "kB" else 1)
    return out


def parse_cpu_line(text: str) -> tuple[int, int] | None:
    """Primeira linha de /proc/stat -> (ocioso, total) em ticks."""
    for line in text.splitlines():
        if line.startswith("cpu "):
            nums = [int(x) for x in line.split()[1:]]
            idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
            return idle, sum(nums[:8])
    return None


def parse_throttled(text: str) -> int | None:
    """'throttled=0xd0008' -> 0xd0008."""
    _, _, val = text.strip().partition("=")
    try:
        return int(val, 16)
    except ValueError:
        return None


def throttle_reasons(value: int | None) -> tuple[list[str], list[str]]:
    """-> (problemas agora, problemas desde que ligou)."""
    if not value:
        return [], []
    now = [THROTTLE_BITS[b] for b in (0, 1, 2, 3) if value & (1 << b)]
    past = [THROTTLE_BITS[b] for b in (16, 17, 18, 19) if value & (1 << b)]
    return now, past


def cpu_percent(sample_s: float = 0.4) -> float | None:
    """Uso de CPU (%) desde a última leitura (ou numa amostra curta, na primeira vez)."""
    global _last_cpu
    first = parse_cpu_line(_read("/proc/stat"))
    if not first:
        return None
    if _last_cpu is None or time.time() - _last_cpu[0] > 120:
        time.sleep(sample_s)
        prev = first
        first = parse_cpu_line(_read("/proc/stat")) or first
    else:
        prev = _last_cpu[1:]
    _last_cpu = (time.time(), *first)
    total = first[1] - prev[1]
    return round(100 * (1 - (first[0] - prev[0]) / total), 1) if total > 0 else None


def services() -> list[dict[str, Any]]:
    keys = [f"{name}.service" for name, _ in SERVICES]
    raw = _run(["systemctl", "--user", "show", *keys, "-p", "Id,ActiveState,MemoryCurrent,ActiveEnterTimestamp"])
    blocks: dict[str, dict[str, str]] = {}
    for block in raw.strip().split("\n\n"):
        kv = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        if kv.get("Id"):
            blocks[kv["Id"]] = kv
    out = []
    for name, label in SERVICES:
        kv = blocks.get(f"{name}.service", {})
        mem = kv.get("MemoryCurrent", "")
        out.append({"id": name, "label": label, "state": kv.get("ActiveState") or "desconhecido",
                    "memory": int(mem) if mem.isdigit() else None, "since": kv.get("ActiveEnterTimestamp") or ""})
    return out


def parse_ps(text: str, limit: int = 6) -> list[dict[str, Any]]:
    """`ps -eo rss=,pcpu=,args=` ordenado por memória -> os processos que mais gastam."""
    out = []
    for line in text.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3 or not parts[0].isdigit():
            continue
        args = parts[2]
        name = args.split()[0].rsplit("/", 1)[-1]
        for key, label in (("health", "Pulse"), ("finance", "Cifra"), ("car", "Torque"), ("learning", "Lume"),
                           ("personal-assistant", "Cassandra"), ("main.py", "Cassandra")):
            if name.startswith("python") and key in args:
                name = label
                break
        out.append({"name": name, "memory": int(parts[0]) * 1024, "cpu": float(parts[1].replace(",", "."))})
        if len(out) >= limit:
            break
    return out


def judge(d: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    """Veredito geral e os motivos: [{"level": "warn|bad", "text"}]."""
    issues: list[dict[str, str]] = []

    def add(level: str, text: str) -> None:
        issues.append({"level": level, "text": text})

    mem = d.get("memory") or {}
    if mem.get("total"):
        free_pct = 100 * mem["available"] / mem["total"]
        if free_pct < 10:
            add("bad", f"Memória quase acabando: só {free_pct:.0f}% livre")
        elif free_pct < 20:
            add("warn", f"Memória apertada: {free_pct:.0f}% livre")
    swap = d.get("swap") or {}
    if swap.get("total") and swap["used"] / swap["total"] > 0.6:
        add("warn", f"Usando muito swap ({100 * swap['used'] / swap['total']:.0f}%): o sistema fica lento")
    disk = d.get("disk") or {}
    if disk.get("total"):
        used = 100 * disk["used"] / disk["total"]
        if used > 90:
            add("bad", f"Disco quase cheio ({used:.0f}%)")
        elif used > 80:
            add("warn", f"Disco enchendo ({used:.0f}%)")
    temp = d.get("temp_c")
    if temp is not None:
        if temp >= 80:
            add("bad", f"Muito quente: {temp:.0f} °C")
        elif temp >= 70:
            add("warn", f"Quente: {temp:.0f} °C")
    for text in d.get("throttle_now") or []:
        add("bad" if text.startswith("Subtensão") else "warn", text)
    if any(t.startswith("Teve subtensão") for t in d.get("throttle_past") or []) and not d.get("throttle_now"):
        add("warn", "Teve subtensão desde que ligou: a fonte é fraca para o Pi")
    load = d.get("load") or []
    if load and d.get("cores") and load[1] > 1.5 * d["cores"]:
        add("warn", f"CPU sobrecarregada (carga média {load[1]:.1f} para {d['cores']} núcleos)")
    for s in d.get("services") or []:
        if s["state"] != "active":
            add("bad" if s["id"] == "cassandra-assistant" else "warn", f"{s['label']} está {s['state']}")
    level = "bad" if any(i["level"] == "bad" for i in issues) else "warn" if issues else "ok"
    return level, issues


def snapshot() -> dict[str, Any]:
    """Tudo de uma vez, para a aba "Saúde do Pi"."""
    if not Path("/proc/meminfo").exists():
        return {"available": False, "reason": "Só funciona no Linux (o Raspberry Pi)."}
    mi = parse_meminfo(_read("/proc/meminfo"))
    total, avail = mi.get("MemTotal", 0), mi.get("MemAvailable", 0)
    disk = shutil.disk_usage("/")
    temp_raw = _read("/sys/class/thermal/thermal_zone0/temp").strip()
    throttled = parse_throttled(_run(["vcgencmd", "get_throttled"]))
    now, past = throttle_reasons(throttled)
    clock = _run(["vcgencmd", "measure_clock", "arm"]).strip().partition("=")[2]
    try:
        uptime = int(float(_read("/proc/uptime").split()[0]))
    except (IndexError, ValueError):
        uptime = None
    try:
        load = [float(x) for x in _read("/proc/loadavg").split()[:3]]
    except ValueError:
        load = []
    d: dict[str, Any] = {
        "available": True,
        "model": _read("/proc/device-tree/model").strip("\x00 \n") or os.uname().nodename,
        "hostname": os.uname().nodename,
        "uptime_s": uptime,
        "cores": os.cpu_count() or 1,
        "cpu_percent": cpu_percent(),
        "cpu_mhz": round(int(clock) / 1e6) if clock.isdigit() else None,
        "load": load,
        "memory": {"total": total, "available": avail, "used": total - avail},
        "swap": {"total": mi.get("SwapTotal", 0), "used": mi.get("SwapTotal", 0) - mi.get("SwapFree", 0)},
        "disk": {"total": disk.total, "used": disk.used, "free": disk.free},
        "temp_c": round(int(temp_raw) / 1000, 1) if temp_raw.lstrip("-").isdigit() else None,
        "throttled": hex(throttled) if throttled is not None else None,
        "throttle_now": now,
        "throttle_past": past,
        "services": services(),
        "top": parse_ps(_run(["ps", "-eo", "rss=,pcpu=,args=", "--sort=-rss"])),
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    d["status"], d["issues"] = judge(d)
    return d
