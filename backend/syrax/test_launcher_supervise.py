"""The UI observes; the core is the brain. A dead UI is restarted (a bounded
number of times) while the core keeps running; a dead core stops SYRAX so the
service starts it again (live 2026-10-10: the UI ended and took the core down)."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("syrax_launcher_sup", ROOT / "syrax.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "LOG", tmp_path / "syrax.log")
    monkeypatch.setattr(mod, "PID_FILE", tmp_path / "syrax.pid")
    monkeypatch.setattr(mod, "_OUTPUT_IS_LOG", False)
    monkeypatch.setattr(mod, "setup", lambda verbose=False: None)
    monkeypatch.setattr(mod, "check_config", lambda: None)
    monkeypatch.setattr(mod, "port_in_use", lambda port: False)
    monkeypatch.setattr(mod, "ui_is_stale", lambda: False)
    monkeypatch.setattr(sys, "argv", ["syrax.py", "--service"])
    monkeypatch.setenv("SYRAX_OPEN_UI", "0")
    return mod


def test_the_decision(launcher):
    sup = launcher.supervise
    assert sup(False, True, [], 1000.0) == "shutdown"
    assert sup(True, True, [], 1000.0) == "ok"
    assert sup(True, False, [], 1000.0) == "restart_ui"
    five = [990.0] * launcher.UI_MAX_RESTARTS
    assert sup(True, False, five, 1000.0) == "give_up_ui"
    assert sup(True, False, [1000.0 - launcher.UI_RESTART_WINDOW_S - 1] * 5, 1000.0) == "restart_ui"  # old restarts expire
    assert sup(True, False, five, 1000.0, ui_given_up=True) == "ok"


def test_a_dying_ui_is_restarted_and_the_core_keeps_running(launcher, monkeypatch):
    ticks = {"n": 0}
    started = []

    class Proc:
        returncode = 1

    class Fake:
        def __init__(self, name, cmd, cwd, log):
            self.name, self.proc, self.born = name, Proc(), ticks["n"]
            started.append(name)

        def alive(self):
            if self.name == "core":
                return ticks["n"] < 12  # the core ends the run after 12 ticks
            return started.count("ui") >= 3 or ticks["n"] - self.born < 2  # the first two UIs die quickly

        def stop(self):
            pass

    def sleep(_):
        ticks["n"] += 1

    monkeypatch.setattr(launcher, "Component", Fake)
    monkeypatch.setattr(launcher.time, "sleep", sleep)
    assert launcher.launch(dev=False, service=True) == 0
    assert started.count("core") == 1 and started.count("ui") == 3
    log = launcher.LOG.read_text(encoding="utf-8")
    assert log.count("restarting it, the core keeps running") == 2 and "core exited (code 1), shutting down" in log
