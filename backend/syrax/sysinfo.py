"""Machine facts that SYRAX reads in several places (resource gate, self-model,
desktop tool), answered the same way on Linux and Windows.

Every function returns None (or a dict of Nones) when the platform has no
answer, so callers never branch on the OS themselves.
"""

from __future__ import annotations

import ctypes
import glob
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

WINDOWS = sys.platform == "win32"


def meminfo() -> Dict[str, Optional[int]]:
    """Total and available RAM in MB."""
    if WINDOWS:
        return _win_meminfo()
    try:
        mem = {}
        for ln in Path("/proc/meminfo").read_text().splitlines():
            k, v = ln.split(":", 1)
            mem[k] = int(v.split()[0]) // 1024
        return {"total_mb": mem.get("MemTotal"), "available_mb": mem.get("MemAvailable")}
    except Exception:
        return {"total_mb": None, "available_mb": None}


def loadavg() -> Optional[List[float]]:
    """1/5/15-minute load averages where the OS keeps them; on Windows a
    single CPU-usage sample scaled to core count, repeated three times so the
    shape is the same for every reader."""
    if not WINDOWS:
        try:
            return [round(x, 2) for x in os.getloadavg()]
        except (OSError, AttributeError):
            return None
    pct = _win_cpu_percent()
    if pct is None:
        return None
    load = round(pct / 100 * (os.cpu_count() or 1), 2)
    return [load, load, load]


def battery() -> Optional[dict]:
    """{"percent", "status", "discharging"} or None on a machine without one."""
    if WINDOWS:
        return _win_battery()
    for bat in sorted(glob.glob("/sys/class/power_supply/BAT*")):
        try:
            pct = int(Path(bat, "capacity").read_text().strip())
            status = Path(bat, "status").read_text().strip()
        except (OSError, ValueError):
            continue
        return {"percent": pct, "status": status, "discharging": status.lower() == "discharging"}
    return None


def uptime_seconds() -> Optional[float]:
    if WINDOWS:
        try:
            return ctypes.windll.kernel32.GetTickCount64() / 1000.0
        except Exception:
            return None
    try:
        return float(Path("/proc/uptime").read_text().split()[0])
    except Exception:
        return None


# ——— Windows, via kernel32 only (no extra packages) ———

class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class _SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong),
    ]


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_ulong), ("dwHighDateTime", ctypes.c_ulong)]


def _ft(ft: _FILETIME) -> int:
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


def _win_meminfo() -> Dict[str, Optional[int]]:
    try:
        st = _MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            raise OSError("GlobalMemoryStatusEx failed")
        return {"total_mb": st.ullTotalPhys // 2**20, "available_mb": st.ullAvailPhys // 2**20}
    except Exception:
        return {"total_mb": None, "available_mb": None}


def _win_battery() -> Optional[dict]:
    try:
        st = _SYSTEM_POWER_STATUS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(st)):
            return None
        if st.BatteryFlag & 128 or st.BatteryLifePercent == 255:  # no system battery / unknown
            return None
        discharging = st.ACLineStatus == 0
        status = "Discharging" if discharging else ("Full" if st.BatteryLifePercent >= 100 else "Charging")
        return {"percent": int(st.BatteryLifePercent), "status": status, "discharging": discharging}
    except Exception:
        return None


def _win_cpu_percent(sample_s: float = 0.15) -> Optional[float]:
    try:
        k32 = ctypes.windll.kernel32

        def times():
            idle, kern, user = _FILETIME(), _FILETIME(), _FILETIME()
            if not k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)):
                raise OSError("GetSystemTimes failed")
            return _ft(idle), _ft(kern) + _ft(user)

        i0, t0 = times()
        time.sleep(sample_s)
        i1, t1 = times()
        total = t1 - t0
        if total <= 0:
            return 0.0
        return round(100.0 * (1 - (i1 - i0) / total), 1)
    except Exception:
        return None
