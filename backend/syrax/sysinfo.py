"""Machine facts that SYRAX reads in several places (resource gate, self-model,
desktop tool), answered the same way on Linux and Windows.

Every function returns None (or a dict of Nones) when the platform has no
answer, so callers never branch on the OS themselves.
"""

from __future__ import annotations

import ctypes
import glob
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"


def meminfo() -> Dict[str, Optional[int]]:
    """Total and available RAM in MB."""
    if WINDOWS:
        return _win_meminfo()
    if MACOS:
        return _mac_meminfo()
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
    shape is the same for every reader (the sample is the average since the
    previous reading; see _win_cpu_percent)."""
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
    if MACOS:
        return _mac_battery()
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
    if MACOS:
        m = re.search(r"sec = (\d+)", _sh("sysctl", "-n", "kern.boottime"))
        return time.time() - int(m.group(1)) if m else None
    try:
        return float(Path("/proc/uptime").read_text().split()[0])
    except Exception:
        return None



def gpu() -> Optional[Dict[str, Any]]:
    """GPU info or None if nvidia-smi is not present or fails."""
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=2,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if WINDOWS else 0,  # the constant exists only on Windows
        )
        if res.returncode != 0:
            return None
        line = res.stdout.strip().splitlines()
        if not line:
            return None
        parts = [p.strip() for p in line[0].split(",")]
        if len(parts) < 4:
            return None
        return {
            "name": parts[0],
            "memory_total_mb": int(parts[1]) if parts[1].isdigit() else None,
            "memory_used_mb": int(parts[2]) if parts[2].isdigit() else None,
            "utilization_pct": int(parts[3]) if parts[3].isdigit() else None,
        }
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, ValueError, IndexError):
        pass

    if WINDOWS:
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", "Get-CimInstance Win32_VideoController | Select-Object -First 1 Name,AdapterRAM | ConvertTo-Json -Compress"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if res.returncode == 0 and res.stdout.strip():
                import json
                data = json.loads(res.stdout.strip())
                if isinstance(data, list) and data:
                    item = data[0]
                elif isinstance(data, dict):
                    item = data
                else:
                    item = None
                if item and isinstance(item, dict):
                    name = item.get("Name")
                    if name:
                        adapter_ram = item.get("AdapterRAM")
                        memory_total_mb = adapter_ram // 1048576 if isinstance(adapter_ram, (int, float)) else None
                        return {
                            "name": name,
                            "memory_total_mb": memory_total_mb,
                            "memory_used_mb": None,
                            "utilization_pct": None,
                        }
        except Exception:
            pass

    return None




# ——— macOS, via sysctl / vm_stat / pmset ———

def _sh(*cmd: str) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return ""


def _mac_meminfo() -> Dict[str, Optional[int]]:
    try:
        total = int(_sh("sysctl", "-n", "hw.memsize").strip())
        vm = _sh("vm_stat")
        page = int(re.search(r"page size of (\d+) bytes", vm).group(1))
        pages = {k.strip(): int(v.strip(" .")) for k, v in (ln.split(":", 1) for ln in vm.splitlines() if ":" in ln and "page size" not in ln)}
        free = sum(pages.get(k, 0) for k in ("Pages free", "Pages inactive", "Pages speculative")) * page
        return {"total_mb": total // 2**20, "available_mb": free // 2**20}
    except Exception:
        return {"total_mb": None, "available_mb": None}


def _mac_battery() -> Optional[dict]:
    out = _sh("pmset", "-g", "batt")
    m = re.search(r"(\d+)%;\s*([\w ]+?);", out)
    if not m:
        return None
    pct, state = int(m.group(1)), m.group(2).strip()
    return {"percent": pct, "status": state.capitalize(), "discharging": state == "discharging"}


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


def _win_system_times() -> Tuple[int, int]:
    """(idle, kernel + user) in 100-ns ticks since boot; kernel time already
    includes idle time, so busy = 1 - idle / total over any interval."""
    idle, kern, user = _FILETIME(), _FILETIME(), _FILETIME()
    if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)):
        raise OSError("GetSystemTimes failed")
    return _ft(idle), _ft(kern) + _ft(user)


# The previous GetSystemTimes reading as (monotonic seconds, idle, total).
# A reading at least _CPU_MIN_GAP_S old is a ready-made window: the next call
# computes CPU % from the delta since it and never sleeps. Only the first call,
# or a call within _CPU_MIN_GAP_S of the previous reading (a window too short
# to mean anything at the ~15.6 ms tick), sleeps sample_s for a fresh window.
_CPU_MIN_GAP_S = 0.1
_cpu_lock = threading.Lock()
_cpu_last: Optional[Tuple[float, int, int]] = None


def _win_cpu_percent(sample_s: float = 0.15) -> Optional[float]:
    """CPU busy percent (0-100) averaged since the previous reading; live
    readers (the 60 s alert loop, hellos) keep that window under a minute."""
    global _cpu_last
    try:
        with _cpu_lock:
            prev = _cpu_last
        if prev is None or time.monotonic() - prev[0] < _CPU_MIN_GAP_S:
            i0, t0 = _win_system_times()
            time.sleep(sample_s)
        else:
            _, i0, t0 = prev
        i1, t1 = _win_system_times()
        now = time.monotonic()
        with _cpu_lock:
            if _cpu_last is None or now >= _cpu_last[0]:
                _cpu_last = (now, i1, t1)
        total = t1 - t0
        if total <= 0:
            return 0.0
        return round(min(100.0, max(0.0, 100.0 * (1 - (i1 - i0) / total))), 1)
    except Exception:
        return None
