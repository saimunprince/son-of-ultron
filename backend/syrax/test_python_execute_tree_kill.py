"""A python_execute timeout kills everything the worker started, not only the worker (2026-10-27 review: a
subprocess pytest or a Popen'd server ran on after the timeout on Windows)."""

import asyncio
import sys
import time

import psutil
import pytest

from syrax import tools
from syrax.tools import AsyncPythonExecute

GRANDCHILD = "import time; time.sleep(120)"


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def code_that_starts_a_tree(pids_file) -> str:
    child = ("import subprocess, sys, time\n"
             f"q = subprocess.Popen([sys.executable, '-c', {GRANDCHILD!r}])\n"
             f"open({str(pids_file)!r}, 'a').write('grandchild %d\\n' % q.pid)\n"
             "time.sleep(120)\n")
    return ("import subprocess, sys, time\n"
            f"p = subprocess.Popen([sys.executable, '-c', {child!r}])\n"
            f"open({str(pids_file)!r}, 'a').write('child %d\\n' % p.pid)\n"
            "time.sleep(120)\n")


def alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


@pytest.mark.parametrize("way", ["psutil", "taskkill"])
def test_a_timeout_kills_the_workers_children_and_grandchildren(tmp_path, monkeypatch, way):
    if way == "taskkill":  # no psutil: Windows' taskkill /T takes the tree
        if sys.platform != "win32":
            pytest.skip("taskkill is Windows'")
        monkeypatch.setattr(tools, "_worker_descendants", lambda proc: None)
    pids_file = tmp_path / "pids.txt"
    pids = {}
    try:
        out = run(AsyncPythonExecute().execute(code=code_that_starts_a_tree(pids_file), timeout=8))
        assert out["success"] is False and out["observation"].startswith("Execution timeout after 8 seconds")
        pids = {k: int(v) for k, v in (ln.split() for ln in pids_file.read_text().splitlines())}
        assert set(pids) == {"child", "grandchild"}  # the tree was up before the timeout
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and any(alive(p) for p in pids.values()):
            time.sleep(0.1)
        assert not [k for k, p in pids.items() if alive(p)]
    finally:
        for p in pids.values():  # never leave a sleeper behind, even when the test fails
            try:
                psutil.Process(p).kill()
            except psutil.Error:
                pass


def test_a_fake_or_foreign_pid_never_names_a_tree():
    killed = []

    class Fake:
        pid = 1  # not this process's child: its "descendants" are never touched

        def is_alive(self):
            return True

        def kill(self):
            killed.append(True)

        def join(self, timeout=None):
            pass

    assert tools._worker_descendants(Fake()) == []
    tools._kill_quietly(Fake())
    assert killed == [True]
