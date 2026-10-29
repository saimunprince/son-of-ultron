"""2026-10-29: SYRAX started from a Claude Code shell carried that session's token in its environment, and every
worker inherited the server's environment: credentials by name, the ssh agent (a push to GitHub as the owner) and the
session bus (the desktop keyring). Own work's workers and confined test runs now drop them, and the launcher drops
the editor session's variables before it starts anything."""

import asyncio
import importlib.util
import os
import sys

from syrax import _confine, tools
from syrax.journal import BACKEND_ROOT

FAKE = {"MY_API_KEY": "k-123", "GITHUB_TOKEN": "ghp_x", "DB_PASSWORD": "p", "SSH_AUTH_SOCK": "/run/user/1/ssh",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1/bus", "CLAUDE_CODE_MESSAGING_TOKEN": "t", "HARMLESS": "ok"}


def test_secret_names_are_recognised():
    for k in FAKE:
        assert _confine.is_secret_env(k) == (k != "HARMLESS"), k
    assert not _confine.is_secret_env("SYRAX_GUARD_PATHS") and not _confine.is_secret_env("PATH")
    env = dict(FAKE)
    assert _confine.scrub_env(env) == sorted(k for k in FAKE if k != "HARMLESS") and env == {"HARMLESS": "ok"}


def test_own_work_s_code_sees_no_secrets(monkeypatch):
    for k, v in FAKE.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(tools, "TASK_KIND", "autonomous")
    monkeypatch.setattr(tools, "WRITE_ROOTS", ())
    code = ("names = sorted(os.environ)\n"
            "child = subprocess.run([sys.executable, '-c', 'import os; print(chr(10).join(k + \"=\" for k in os.environ))'], "
            "capture_output=True, text=True).stdout\n"
            "print([k for k in " + repr(list(FAKE)) + " if k in names or k + '=' in child])")
    out = asyncio.new_event_loop().run_until_complete(tools.AsyncPythonExecute().execute(code=code, timeout=60))
    assert "['HARMLESS']" in out["observation"], out


def test_a_human_request_keeps_its_environment(monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "k-123")
    monkeypatch.setattr(tools, "TASK_KIND", "conversation")
    out = asyncio.new_event_loop().run_until_complete(
        tools.AsyncPythonExecute().execute(code="print(os.environ.get('MY_API_KEY'))", timeout=60))
    assert "k-123" in out["observation"]  # the human may hand a key to their own script


def test_the_launcher_drops_the_editor_session_s_variables():
    spec = importlib.util.spec_from_file_location("syrax_launcher_env", BACKEND_ROOT.parent / "syrax.py")
    launcher = importlib.util.module_from_spec(spec)
    sys.modules["syrax_launcher_env"] = launcher
    spec.loader.exec_module(launcher)
    env = {"CLAUDE_CODE_MESSAGING_TOKEN": "t", "CLAUDECODE": "1", "PATH": os.environ.get("PATH", "")}
    assert launcher.drop_foreign_session_env(env) == ["CLAUDECODE", "CLAUDE_CODE_MESSAGING_TOKEN"] and list(env) == ["PATH"]
