"""EVOLUTION_PLAN wave 3 (direction 201 visual perception): on this GNOME (Wayland) PC no screenshot command exists
(gnome-screenshot, grim, scrot: none), so the desktop tool's screenshot failed and no brain could see the screen. GNOME's
Screenshot portal is used instead, through a helper under the system python3; the shot moves into the workspace."""

import json

import pytest

from syrax import desktop as D


def test_the_portal_answer_is_read_and_checked(tmp_path):
    shot = tmp_path / "Screenshot.png"
    shot.write_bytes(b"\\x89PNG fake")
    assert D._portal_screenshot(runner=lambda: json.dumps({"ok": True, "path": str(shot)})) == str(shot)
    with pytest.raises(RuntimeError, match="refused"):
        D._portal_screenshot(runner=lambda: json.dumps({"ok": False, "error": "the screenshot was refused (code 1)"}))
    with pytest.raises(RuntimeError, match="does not exist"):
        D._portal_screenshot(runner=lambda: json.dumps({"ok": True, "path": str(tmp_path / "gone.png")}))


def test_tests_never_read_the_real_screen():
    with pytest.raises(RuntimeError, match="off here"):
        D._portal_screenshot()
