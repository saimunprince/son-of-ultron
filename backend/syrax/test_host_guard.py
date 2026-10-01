"""Code SYRAX runs may not kill processes it did not start, power the machine
off or change system configuration (live 2026-10-01: a skill it wrote
terminated every process above 20 % memory)."""

import asyncio
import subprocess
import sys

from syrax import guard
from syrax.tools import AsyncPythonExecute


def run(code):
    return asyncio.run(AsyncPythonExecute().execute(code, timeout=60))


def test_commands_that_harm_the_host_are_recognised():
    assert guard.command_harm(["taskkill", "/f", "/im", "chrome.exe"]) == ["kills processes"]
    assert guard.command_harm("shutdown /s /t 0") == ["powers the machine off or restarts it"]
    assert guard.command_harm("powershell Stop-Process -Name code") == ["kills processes"]
    assert guard.command_harm("reg delete HKCU\\Software\\X /f") == ["changes system configuration"]
    assert guard.command_harm(["git", "status"]) == [] and guard.command_harm("pip list") == []


def test_python_execute_cannot_kill_a_process_it_did_not_start():
    victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        out = run(f"import os, signal\ntry:\n    os.kill({victim.pid}, signal.SIGTERM)\n    print('KILLED')\nexcept PermissionError as e:\n    print('REFUSED', e)")
        assert "REFUSED" in out["observation"] and victim.poll() is None
        out = run(f"import psutil\ntry:\n    psutil.Process({victim.pid}).terminate()\n    print('KILLED')\nexcept PermissionError as e:\n    print('REFUSED', e)")
        assert "REFUSED" in out["observation"] and victim.poll() is None
        out = run(f"import subprocess\ntry:\n    subprocess.run(['taskkill', '/pid', '{victim.pid}'])\n    print('KILLED')\nexcept PermissionError as e:\n    print('REFUSED', e)")
        assert "REFUSED" in out["observation"] and victim.poll() is None
    finally:
        victim.kill()


def test_python_execute_still_runs_and_stops_its_own_processes():
    code = ("import subprocess, sys\n"
            "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            "p.terminate(); p.wait(10)\n"
            "print('own child stopped', subprocess.run([sys.executable, '-c', 'print(42)'], capture_output=True, text=True).stdout.strip())")
    out = run(code)
    assert "own child stopped 42" in out["observation"], out
