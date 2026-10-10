"""A worker whose pipe closed but whose process is not reaped yet is exiting,
not hanging: python_execute reports its exit code, not a timeout (the gate
hit this race under load on 2026-10-10)."""

import asyncio
import multiprocessing

from syrax.tools import AsyncPythonExecute


class LingeringProcess:
    """Closes its end of the pipe at once, but reports alive until joined."""

    def __init__(self, target=None, args=(), daemon=None):
        self.args = args
        self.pid = None
        self.exitcode = None

    def start(self):
        self.pid = 1
        self.args[1].close()  # the child's end: EOF without a result

    def is_alive(self):
        return self.pid is not None and self.exitcode is None

    def join(self, timeout=None):
        self.exitcode = 3  # reaping takes a moment

    def kill(self):
        self.exitcode = -9


def test_eof_before_reaping_is_an_exit_not_a_timeout(monkeypatch):
    monkeypatch.setattr(multiprocessing, "Process", LingeringProcess)
    out = asyncio.new_event_loop().run_until_complete(AsyncPythonExecute().execute(code="print(1)", timeout=60))
    assert out == {"observation": "Error: the python_execute worker exited with code 3 before returning a result", "success": False}
