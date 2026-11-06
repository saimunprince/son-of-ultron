"""Host check (2026-11-05): verdicts, the public report keeps no private data, black screenshots, quiet _run."""

import asyncio
import io
import sys
from pathlib import Path

from syrax import hostcheck


def test_verdicts():
    assert hostcheck.verdict("yes", True) == "OK"
    assert hostcheck.verdict("no: why", False) == "NO (as predicted)"
    assert hostcheck.verdict("yes", False) == "MISMATCH"
    assert hostcheck.verdict("no: why", True) == "MISMATCH"
    assert hostcheck.verdict("yes", None) == "NOT TRIED"


def test_private_hides_home_and_user(monkeypatch):
    monkeypatch.setenv("USER", "princeuser")
    monkeypatch.setenv("USERNAME", "princeuser")
    home = str(Path.home())
    out = hostcheck.private(f"no file at {home}/x.txt owned by PrinceUser\n  next line")
    assert home not in out and "~/x.txt" in out and "princeuser" not in out.lower() and "\n" not in out
    assert len(hostcheck.private("a" * 999)) == 200


def test_black_screenshot():
    from PIL import Image

    def png(color):
        buf = io.BytesIO()
        Image.new("RGB", (64, 48), color).save(buf, "PNG")
        return buf.getvalue()

    assert hostcheck.black(png((0, 0, 0))) is True
    assert hostcheck.black(png((200, 30, 30))) is False
    assert hostcheck.black(b"not a picture") is None


def test_report_marks_mismatch_and_slug():
    p = {"name": "Windows 11 (build 10.0.26100)", "kernel": "11", "arch": "AMD64", "desktop": "Windows shell",
         "display": "windows", "tools": {"adb": True, "ffmpeg": False}, "os": "Windows"}
    rows = [{"action": "clipboard", "predicted": "yes", "verdict": "MISMATCH", "detail": "a|b"},
            {"action": "window", "predicted": "yes", "verdict": "OK", "detail": ""}]
    text = hostcheck.report(p, rows, when="2026-11-05 10:00")
    assert "Result: 1 MISMATCH" in text and "| clipboard | yes | MISMATCH | a/b |" in text
    assert "Helper programs found: adb" in text and "ffmpeg" not in text
    assert hostcheck.slug("Windows", "Windows shell", "windows") == "windows-windowsshell-windows"


def test_quiet_run_does_not_wait_for_a_child_holding_the_pipes():
    """wl-copy and xclip leave a child holding stdout: reading it waited for the whole timeout."""
    from syrax import desktop

    code = "import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); print('x')"
    got = asyncio.run(desktop._run(sys.executable, "-c", code, timeout=8, quiet=True))
    assert got[0] == 0


def test_the_gate_report_lists_failing_tests_and_hides_home():
    import json

    home = str(Path.home())
    raw = "warning first\n" + json.dumps({"status": "BLOCKED", "git_head": "ce7bf97abc", "gates": [
        {"name": "pytest", "status": "FAIL", "required": True, "duration_ms": 260000,
         "evidence": f"FAILED syrax/test_x.py::test_a - assert 1 in {home}/y\nERROR syrax/test_y.py\n.... passed"},
        {"name": "performance", "status": "PASS", "required": False, "duration_ms": 200, "evidence": ""}]})
    g = hostcheck.run_gate(runner=lambda: raw)
    assert g["status"] == "BLOCKED" and g["head"] == "ce7bf97" and len(g["failing"]) == 2
    assert home not in g["failing"][0] and "~/y" in g["failing"][0]
    text = hostcheck.gate_report(g)
    assert "| pytest | FAIL | 260 |" in text and "| performance (optional) | PASS | 0 |" in text and "`ERROR syrax/test_y.py`" in text
    assert hostcheck.run_gate(runner=lambda: "crashed")["status"] == "NOT_RUN"
