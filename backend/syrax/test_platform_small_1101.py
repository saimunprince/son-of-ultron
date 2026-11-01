"""Audit 2026-11-01 (integrations I-07, I-11): on macOS, keyboard, mouse and dark mode went to the GNOME backend and
failed with portal errors; amixer's mute state was never read, so a mute's undo was wrong; a failed gsettings read
was taken as "off". macOS says it is not built; amixer reports "(muted)"; a failed read changes nothing."""

import asyncio

import pytest

from syrax import desktop, linuxinput


def test_macos_says_the_hands_are_not_built(monkeypatch):
    monkeypatch.setattr(desktop, "MACOS", True)
    monkeypatch.setattr(desktop, "WINDOWS", False)
    with pytest.raises(RuntimeError, match="not built for macOS"):
        desktop._hands_module().type_text("hi")


def test_amixer_reports_the_mute_state(monkeypatch):
    async def fake(*args, **kw):
        if args[:2] == ("amixer", "get"):
            return 0, "Front Left: Playback 26214 [40%] [off]", ""
        return 0, "", ""

    monkeypatch.setattr(desktop, "_run", fake)
    monkeypatch.setattr(desktop, "WINDOWS", False)
    monkeypatch.setattr(desktop, "MACOS", False)
    monkeypatch.setattr(desktop.shutil, "which", lambda n: "/usr/bin/amixer" if n == "amixer" else None)
    out = asyncio.run(desktop.DesktopControl()._volume_raw("get"))
    assert out.output == "Volume 40% (muted)."


def test_a_failed_scheme_read_changes_nothing(monkeypatch):
    calls = []

    class R:
        returncode, stdout, stderr = 1, "", "No such schema"

    monkeypatch.delenv("SYRAX_NO_REAL_INPUT", raising=False)
    monkeypatch.setattr(linuxinput.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or R())
    with pytest.raises(RuntimeError, match="could not read"):
        linuxinput.dark_mode("on")
    assert all("set" not in c for c in calls)
