"""Live 2026-10-29 (first Linux quality runs): python_execute code that ran `python` or `pytest` by name failed eight
times with "No such file or directory" (Ubuntu has only python3; the venv is never activated). The interpreter's bin
folder now leads PATH, so the names resolve to the venv's own programs, in every task kind."""

import asyncio
import os
import sys

from syrax import tools


def test_the_venv_bin_leads_path():
    assert os.environ["PATH"].split(os.pathsep)[0] == os.path.dirname(os.path.abspath(sys.executable))


def test_python_and_pytest_run_by_name_from_python_execute(monkeypatch):
    for kind in ("conversation", "autonomous"):
        monkeypatch.setattr(tools, "TASK_KIND", kind)
        monkeypatch.setattr(tools, "WRITE_ROOTS", ())
        out = asyncio.new_event_loop().run_until_complete(tools.AsyncPythonExecute().execute(code=(
            "a = subprocess.run(['python', '-c', 'print(6*7)'], capture_output=True, text=True).stdout.strip()\n"
            "b = subprocess.run(['pytest', '--version'], capture_output=True, text=True)\n"
            "print(a, b.returncode)"), timeout=60))
        assert "42 0" in out["observation"], (kind, out)
