"""Resource awareness for 24/7 operation: what the machine can afford right now.

snapshot()  → measured facts (CPU load, RAM, disk, battery, clock/quiet hours);
              anything unmeasurable is None.
pressure()  → a reason string when SYRAX should not start optional work, else None.

Thresholds are conservative for a laptop that the owner is also using.
"""

from __future__ import annotations

import glob
import os
import shutil
import time
from pathlib import Path
from typing import Optional, Tuple

from syrax.journal import BACKEND_ROOT

LOAD_PER_CORE_MAX = 1.5
MIN_FREE_MB = 1024
MIN_DISK_FREE_GB = 2.0
MIN_BATTERY_PCT_ON_BATTERY = 30


def quiet_hours() -> Optional[Tuple[int, int]]:
    """SYRAX_QUIET_HOURS="23-7" → (23, 7). None when unset or malformed."""
    raw = os.getenv("SYRAX_QUIET_HOURS", "").strip()
    if not raw:
        return None
    try:
        a, b = raw.split("-", 1)
        start, end = int(a), int(b)
    except ValueError:
        return None
    if not (0 <= start <= 23 and 0 <= end <= 23) or start == end:
        return None
    return start, end


def in_quiet_hours(hour: Optional[int] = None) -> bool:
    window = quiet_hours()
    if window is None:
        return False
    start, end = window
    h = time.localtime().tm_hour if hour is None else hour
    if start < end:
        return start <= h < end
    return h >= start or h < end  # wraps past midnight


def battery() -> Optional[dict]:
    for bat in sorted(glob.glob("/sys/class/power_supply/BAT*")):
        try:
            pct = int(Path(bat, "capacity").read_text().strip())
            status = Path(bat, "status").read_text().strip()
        except (OSError, ValueError):
            continue
        return {"percent": pct, "status": status, "discharging": status.lower() == "discharging"}
    return None


def snapshot(root: Path = BACKEND_ROOT) -> dict:
    try:
        load = [round(x, 2) for x in os.getloadavg()]
    except OSError:
        load = None
    cores = os.cpu_count() or 1
    total_mb = avail_mb = None
    try:
        for ln in open("/proc/meminfo"):
            if ln.startswith("MemTotal:"):
                total_mb = int(ln.split()[1]) // 1024
            elif ln.startswith("MemAvailable:"):
                avail_mb = int(ln.split()[1]) // 1024
    except OSError:
        pass
    try:
        du = shutil.disk_usage(str(root))
        disk = {"free_gb": round(du.free / 2**30, 2), "total_gb": round(du.total / 2**30, 1)}
    except OSError:
        disk = None
    return {
        "ts": time.time(),
        "cpu": {"cores": cores, "load_1_5_15": load, "load_per_core": round(load[0] / cores, 2) if load else None},
        "memory_mb": {"total_mb": total_mb, "available_mb": avail_mb},
        "disk": disk,
        "battery": battery(),
        "quiet_hours": {"window": quiet_hours(), "active": in_quiet_hours()},
    }


def pressure(snap: Optional[dict] = None) -> Optional[str]:
    s = snap or snapshot()
    if s["quiet_hours"]["active"]:
        w = s["quiet_hours"]["window"]
        return f"quiet hours {w[0]:02d}:00-{w[1]:02d}:00"
    lpc = s["cpu"]["load_per_core"]
    if lpc is not None and lpc > LOAD_PER_CORE_MAX:
        return f"cpu load {s['cpu']['load_1_5_15'][0]} on {s['cpu']['cores']} cores"
    avail = s["memory_mb"]["available_mb"]
    if avail is not None and avail < MIN_FREE_MB:
        return f"only {avail} MB RAM available"
    if s["disk"] and s["disk"]["free_gb"] < MIN_DISK_FREE_GB:
        return f"only {s['disk']['free_gb']} GB disk free"
    b = s["battery"]
    if b and b["discharging"] and b["percent"] < MIN_BATTERY_PCT_ON_BATTERY:
        return f"on battery at {b['percent']}%"
    return None
