"""screen_brightness: the right WMI commands, clamped levels, the old level
reported for undo, and an unsupported display is an error. The real screen is
never touched by these tests."""

import asyncio
import importlib.util
import subprocess
from pathlib import Path

_spec = importlib.util.spec_from_file_location("prebuilt_brightness_skill", Path(__file__).with_name("skill.py"))
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


class FakeScreen:
    def __init__(self, level=40, supported=True):
        self.level, self.supported, self.commands = level, supported, []

    def __call__(self, command, timeout=20.0):
        self.commands.append(command)
        if not self.supported:
            return subprocess.CompletedProcess([], 1, "", "Get-CimInstance : Not supported")
        if "WmiSetBrightness" in command:
            self.level = int(command.split("Brightness=")[1].split("}")[0])
            return subprocess.CompletedProcess([], 0, "", "")
        return subprocess.CompletedProcess([], 0, f"{self.level}\n", "")


def run(**kw):
    return asyncio.run(mod.Skill().execute(**kw))


def test_get_and_set_with_the_old_level_reported(monkeypatch):
    screen = FakeScreen(40)
    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "powershell", screen)
    assert run(action="get").output == "Screen brightness is 40%."
    assert run(action="set", level=70).output == "Screen brightness 40% -> 70% (to undo, set it to 40)."
    assert run(action="set", level=150).output.startswith("Screen brightness 70% -> 100%")
    assert "WmiMonitorBrightnessMethods" in screen.commands[-2]


def test_an_unsupported_display_or_bad_input_is_an_error(monkeypatch):
    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "powershell", FakeScreen(supported=False))
    assert "does not expose brightness" in run(action="get").error
    monkeypatch.setattr(mod, "powershell", FakeScreen(50))
    assert "needs a level" in run(action="set").error
    assert "get or set" in run(action="dim").error


def test_other_systems_are_told_plainly(monkeypatch):
    monkeypatch.setattr(mod.sys, "platform", "linux")
    assert "only supported on Windows" in run(action="get").error


def test_the_skill_declares_what_it_does():
    s = mod.Skill()
    assert s.name == "screen_brightness" and s.risk == "SYSTEM"
