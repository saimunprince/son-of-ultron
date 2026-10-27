"""winctl focus: a maximized window stays maximized, a minimized one is restored, and a refused switch is reported as
refused, never as "focused." (2026-10-27 review). The win32 calls are faked: no real window is touched."""

import pytest

from syrax import winctl

HWND = 0x1A2B


class FakeUser32:
    def __init__(self, iconic=False, allowed=True, front_after=None):
        self.iconic, self.allowed, self.front = iconic, allowed, 0x9999
        self.front_after = front_after
        self.calls = []

    def IsIconic(self, hwnd):
        self.calls.append(("IsIconic", hwnd))
        return 1 if self.iconic else 0

    def ShowWindow(self, hwnd, cmd):
        self.calls.append(("ShowWindow", hwnd, cmd))
        return 1

    def SetForegroundWindow(self, hwnd):
        self.calls.append(("SetForegroundWindow", hwnd))
        if self.allowed:
            self.front = hwnd
        return 1 if self.allowed else 0

    def GetForegroundWindow(self):
        return self.front if self.front_after is None else self.front_after


@pytest.fixture
def fake(monkeypatch):
    def make(**kw):
        u = FakeUser32(**kw)
        monkeypatch.setattr(winctl, "_user32", lambda: u)
        monkeypatch.setattr(winctl, "windows", lambda: [(HWND, "Report.docx - Word")])
        return u
    return make


def test_focusing_a_maximized_window_never_restores_it(fake):
    u = fake(iconic=False)
    assert winctl.act("focus", "report") == "Report.docx - Word: focused."
    assert not [c for c in u.calls if c[0] == "ShowWindow"]


def test_focusing_a_minimized_window_restores_it_first(fake):
    u = fake(iconic=True)
    assert winctl.act("focus", "report") == "Report.docx - Word: focused."
    assert ("ShowWindow", HWND, winctl.SW_RESTORE) in u.calls
    assert u.calls.index(("ShowWindow", HWND, winctl.SW_RESTORE)) < u.calls.index(("SetForegroundWindow", HWND))


def test_a_refused_switch_is_reported_not_called_focused(fake):
    fake(allowed=False)
    with pytest.raises(OSError, match="not focused"):
        winctl.act("focus", "report")


def test_a_switch_that_left_another_window_in_front_is_not_focused(fake):
    fake(allowed=True, front_after=0x7777)
    with pytest.raises(OSError, match="not focused"):
        winctl.act("focus", "report")


def test_a_sign_extended_handle_is_the_same_window(fake):
    fake(allowed=True, front_after=HWND | ~0xFFFFFFFF)
    assert winctl.act("focus", "report").endswith("focused.")
