"""The launcher steps aside only for a SYRAX that really answers, and says
why it did not start (live 2026-10-10: another app took port 3000, a
self-restart stepped aside without a word, and SYRAX stayed down)."""

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("syrax_launcher", ROOT / "syrax.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "LOG", tmp_path / "syrax.log")
    monkeypatch.setattr(mod, "_OUTPUT_IS_LOG", False)
    monkeypatch.setattr(mod, "setup", lambda verbose=False: None)
    monkeypatch.setattr(mod, "check_config", lambda: None)
    monkeypatch.setattr(sys, "argv", ["syrax.py", "--service"])
    return mod


class Health:
    def __init__(self, body):
        self.status, self._body = 200, json.dumps(body).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_a_busy_ui_port_held_by_another_app_is_a_loud_failure(launcher, monkeypatch):
    monkeypatch.setattr(launcher, "port_in_use", lambda port: port == launcher.UI_PORT)
    monkeypatch.setattr(launcher.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("refused")))
    with pytest.raises(SystemExit) as e:
        launcher.launch(dev=False, service=True)
    assert e.value.code == 1
    log = launcher.LOG.read_text(encoding="utf-8")
    assert f"port {launcher.UI_PORT} is in use by another program" in log and "SYRAX_UI_PORT" in log


def test_another_program_answering_health_is_not_syrax(launcher, monkeypatch):
    monkeypatch.setattr(launcher.urllib.request, "urlopen", lambda *a, **k: Health({"name": "nova", "status": "ok"}))
    assert launcher.syrax_answers() is False
    monkeypatch.setattr(launcher.urllib.request, "urlopen", lambda *a, **k: Health({"name": "SYRAX", "status": "online"}))
    assert launcher.syrax_answers() is True


def test_a_running_syrax_is_stepped_aside_for_and_the_log_says_so(launcher, monkeypatch):
    monkeypatch.setattr(launcher, "port_in_use", lambda port: True)
    monkeypatch.setattr(launcher.urllib.request, "urlopen", lambda *a, **k: Health({"name": "SYRAX", "status": "online"}))
    assert launcher.launch(dev=False, service=True) == 0
    assert "stepping aside" in launcher.LOG.read_text(encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["syrax.py"])
    with pytest.raises(SystemExit):
        launcher.launch(dev=False, service=False)  # a human start says it plainly
