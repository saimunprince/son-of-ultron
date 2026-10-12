"""Start with Windows (live 2026-10-12: Prince did not want SYRAX opening at
every boot and asked for an on/off in the UI): the switch writes and removes
exactly the Startup entry syrax.py --install-service writes, never touches the
real Startup folder in tests, is journaled, and reaches the UI in hello."""

import importlib.util
from pathlib import Path

import pytest

from syrax import startup
from syrax.test_bridge import ORIGIN, TestClient, get_journal, recv_until, script, server  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SYRAX_STARTUP_DIR", str(tmp_path / "Startup"))
    monkeypatch.setattr(startup.sys, "platform", "win32")
    return tmp_path / "Startup"


def test_on_writes_the_installers_entry_and_off_removes_it(folder):
    assert startup.status() == {"supported": True, "enabled": False, "how": "Startup folder (SYRAX.vbs)"}
    assert startup.set_enabled(True)["enabled"] and (folder / "SYRAX.vbs").is_file()
    text = (folder / "SYRAX.vbs").read_bytes().decode("utf-8")
    assert text.startswith('CreateObject("WScript.Shell").Run """') and text.endswith('""--service""", 0, False\r\n')
    assert str(ROOT / "syrax.py") in text
    assert startup.set_enabled(False)["enabled"] is False and not (folder / "SYRAX.vbs").exists()
    assert startup.set_enabled(False)["enabled"] is False  # off twice is fine


def test_the_entry_is_the_one_the_launcher_writes(folder):
    spec = importlib.util.spec_from_file_location("syrax_launcher_boot", ROOT / "syrax.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    args = " ".join(f'""{a}""' for a in mod.launcher_cmd(hidden=True))
    assert startup.vbs_text() == f'CreateObject("WScript.Shell").Run "{args}", 0, False\r\n'


def test_other_systems_are_reported_not_guessed(monkeypatch):
    monkeypatch.setattr(startup.sys, "platform", "linux")
    assert startup.status()["supported"] is False
    with pytest.raises(RuntimeError):
        startup.set_enabled(True)


def test_the_ui_switch_is_journaled_and_hello_carries_it(script, folder):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        hello, _ = recv_until(ws, "hello")
        assert hello["startup"] == {"supported": True, "enabled": False, "how": "Startup folder (SYRAX.vbs)"}
        ws.send_json({"type": "startup", "enabled": True})
        st, _ = recv_until(ws, "startup_status")
        assert st["enabled"] is True and (folder / "SYRAX.vbs").is_file()
        ws.send_json({"type": "startup", "enabled": False})
        st, _ = recv_until(ws, "startup_status")
        assert st["enabled"] is False and not (folder / "SYRAX.vbs").exists()
    toggles = [e["payload"]["enabled"] for e in get_journal().recent_events(200) if e["type"] == "startup.toggled"]
    assert toggles[-2:] == [True, False]
