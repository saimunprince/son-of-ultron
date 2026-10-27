"""Live 2026-10-27: a short python_execute call took 2.9-3.3 s (journal median) because Windows' spawn re-imports the
parent's __main__ (syrax.server, the whole server and agent) in every worker before the code runs; with __main__
hidden while the worker starts, the same call took 0.13-0.20 s. start_without_main hides __main__'s __spec__ and
__file__ for exactly the start and puts them back however it ends."""

import sys
import types

import pytest

from syrax import tools
from syrax.tools import AsyncPythonExecute, start_without_main


class FakeProc:
    def __init__(self, fail=False):
        self.seen = None
        self.fail = fail

    def start(self):
        main = sys.modules["__main__"]
        self.seen = (getattr(main, "__spec__", "absent"), getattr(main, "__file__", "absent"))
        if self.fail:
            raise OSError("spawn failed")


@pytest.fixture
def fake_main(monkeypatch):
    main = types.ModuleType("__main__")
    main.__spec__ = types.SimpleNamespace(name="syrax.server")
    main.__file__ = "C:/x/syrax/server.py"
    monkeypatch.setitem(sys.modules, "__main__", main)
    return main


def test_the_start_sees_no_main_module_and_it_comes_back(fake_main):
    proc = FakeProc()
    start_without_main(proc)
    assert proc.seen == (None, "absent")
    assert fake_main.__spec__.name == "syrax.server" and fake_main.__file__ == "C:/x/syrax/server.py"


def test_a_failed_start_puts_the_main_module_back(fake_main):
    with pytest.raises(OSError):
        start_without_main(FakeProc(fail=True))
    assert fake_main.__spec__.name == "syrax.server" and fake_main.__file__ == "C:/x/syrax/server.py"


def test_a_main_without_a_file_stays_without_one(monkeypatch):
    main = types.ModuleType("__main__")
    main.__spec__ = None
    monkeypatch.setitem(sys.modules, "__main__", main)
    start_without_main(FakeProc())
    assert main.__spec__ is None and not hasattr(main, "__file__")


def test_python_execute_starts_its_worker_this_way(monkeypatch):
    used = []
    real = tools.start_without_main
    monkeypatch.setattr(tools, "start_without_main", lambda proc: used.append(proc) or real(proc))
    import asyncio

    out = asyncio.run(AsyncPythonExecute().execute(code="print(6*7)"))
    assert "42" in str(out) and len(used) == 1
