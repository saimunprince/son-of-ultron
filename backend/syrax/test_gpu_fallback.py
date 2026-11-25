"""SYRAX's own 17fd802 (objective #95, reverted by its quality check) meant to let Windows find a GPU when
nvidia-smi fails, and still returned None first. A failed or empty nvidia-smi now falls through to Windows' own
GPU list; an NVIDIA answer is used as before."""

import json

from syrax import sysinfo


class Res:
    def __init__(self, code, out):
        self.returncode, self.stdout = code, out


def fake_run(nvidia):
    def run(argv, **kw):
        if argv[0] == "nvidia-smi":
            return nvidia
        return Res(0, json.dumps({"Name": "AMD Radeon Vega", "AdapterRAM": 2 * 1048576 * 1024}))
    return run


def test_a_failed_nvidia_smi_falls_through_to_windows(monkeypatch):
    monkeypatch.setattr(sysinfo, "WINDOWS", True)
    monkeypatch.setattr(sysinfo.subprocess, "run", fake_run(Res(9, "NVIDIA-SMI has failed: no driver\n")))
    assert sysinfo.gpu() == {"name": "AMD Radeon Vega", "memory_total_mb": 2048, "memory_used_mb": None, "utilization_pct": None}


def test_an_nvidia_answer_is_used(monkeypatch):
    monkeypatch.setattr(sysinfo, "WINDOWS", True)
    monkeypatch.setattr(sysinfo.subprocess, "run", fake_run(Res(0, "RTX 4060, 8188, 512, 7\n")))
    assert sysinfo.gpu() == {"name": "RTX 4060", "memory_total_mb": 8188, "memory_used_mb": 512, "utilization_pct": 7}


def test_off_windows_no_nvidia_is_none(monkeypatch):
    monkeypatch.setattr(sysinfo, "WINDOWS", False)
    monkeypatch.setattr(sysinfo.subprocess, "run", fake_run(Res(9, "")))
    assert sysinfo.gpu() is None
