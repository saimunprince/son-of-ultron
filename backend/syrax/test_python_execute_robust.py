"""python_execute never freezes the server: no multiprocessing.Manager, the
worker starts off the event loop with a deadline, and a worker that dies
without a result is reported (live 2026-10-10: the Manager's process died at
start and SYRAX froze for 20 minutes)."""

import asyncio
import threading
import time

import multiprocessing

from syrax import tools
from syrax.tools import AsyncPythonExecute


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_code_runs_without_a_manager(monkeypatch):
    def no_manager(*a, **k):
        raise AssertionError("python_execute must not start a multiprocessing.Manager")

    monkeypatch.setattr(multiprocessing, "Manager", no_manager)
    out = run(AsyncPythonExecute().execute(code="print(6 * 7)", timeout=60))
    assert out == {"observation": "42\n", "success": True}


def test_a_worker_that_dies_without_a_result_is_reported_not_waited_for():
    t0 = time.monotonic()
    out = run(AsyncPythonExecute().execute(code="import os\nos._exit(3)", timeout=60))
    assert out["success"] is False and "exited with code 3" in out["observation"]
    assert time.monotonic() - t0 < 30  # not the 60 s timeout


def test_sys_exit_and_timeouts_still_answer():
    out = run(AsyncPythonExecute().execute(code="import sys\nprint('before')\nsys.exit(0)", timeout=60))
    assert out["success"] is False  # the code did not finish; it is not reported as a hang either
    out = run(AsyncPythonExecute().execute(code="import time\ntime.sleep(30)", timeout=1))
    assert out == {"observation": "Execution timeout after 1 seconds", "success": False}


def test_a_stuck_worker_start_does_not_freeze_the_event_loop(monkeypatch):
    release = threading.Event()
    killed = []

    class StuckProcess:
        pid = None

        def __init__(self, *a, **k):
            pass

        def start(self):  # the blocking part that froze SYRAX
            release.wait(10)
            self.pid = 1

        def is_alive(self):
            return self.pid is not None

        def kill(self):
            killed.append(True)
            self.pid = None

        def join(self, timeout=None):
            pass

    monkeypatch.setattr(tools, "START_TIMEOUT_S", 0.5)
    monkeypatch.setattr(multiprocessing, "Process", StuckProcess)

    async def scenario():
        ticks = []

        async def ticker():
            while True:
                ticks.append(time.monotonic())
                await asyncio.sleep(0.05)

        tk = asyncio.ensure_future(ticker())
        t0 = time.monotonic()
        out = await AsyncPythonExecute().execute(code="print(1)", timeout=60)
        took = time.monotonic() - t0
        tk.cancel()
        release.set()  # the stuck start finishes later; its process is killed
        await asyncio.sleep(0.3)
        return out, took, ticks

    out, took, ticks = run(scenario())
    assert out["success"] is False and "could not start a worker process" in out["observation"] and "nothing ran" in out["observation"]
    assert took < 3
    assert len(ticks) >= 5  # the loop kept running while the start was stuck
    assert killed == [True]
