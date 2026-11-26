"""On GNOME Wayland with the Screenshot portal off (it flashes), a flash-free Fingerprint of the accessibility tree and
the window in front stands in for the screen glance (2026-11-26).

Nothing here reads the real screen or the accessibility bus: the helper's output, the focus extension and the hands
are fakes, so nothing is typed, pressed or clicked.
"""

import asyncio
import json
import subprocess
import types

import pytest

from syrax import claims, desktop as D
from syrax import gnomefocus, linuxinput

FRONT = {"title": "Notes", "wm_class": "gnome-text-editor"}


def helper(parts, ok=True):
    return json.dumps({"ok": ok, "parts": parts, "nodes": 42})


@pytest.fixture
def tree(monkeypatch):
    """A Linux GNOME Wayland desktop without pixels: no grabber, the portal off, faked helper and focus extension."""
    state = {"out": [], "focus": [], "calls": []}
    monkeypatch.delenv("SYRAX_NO_REAL_INPUT", raising=False)
    monkeypatch.delenv("SYRAX_SCREEN_TREE", raising=False)
    monkeypatch.setattr(D, "WINDOWS", False)
    monkeypatch.setattr(D, "MACOS", False)
    monkeypatch.setattr(D, "_x11", lambda: False)
    monkeypatch.setattr(D, "_portal_allowed", lambda: False)
    monkeypatch.setattr(D.shutil, "which", lambda tool: None)
    monkeypatch.setattr(linuxinput, "SYSTEM_PY", __file__)  # a file that exists

    def fake_run(args, **kw):
        state["calls"].append(list(args))
        out = state["out"].pop(0) if state["out"] else ""
        if isinstance(out, Exception):
            raise out
        return types.SimpleNamespace(stdout=out, stderr="", returncode=0)

    monkeypatch.setattr(D.subprocess, "run", fake_run)
    monkeypatch.setattr(gnomefocus, "read", lambda: state["focus"].pop(0) if state["focus"] else None)
    return state


def test_glance_falls_back_to_the_tree_on_wayland_without_the_portal(tree):
    tree["out"] = [helper({"windows": ["w1", True], "front": ["f1", True], "shell": ["s1", True]})]
    tree["focus"] = [FRONT]
    got = D.glance()
    assert isinstance(got, D.Fingerprint)
    assert set(got.parts) == {"focus", "windows", "front", "shell"}
    assert "Notes" not in repr(got.parts)  # only hashes are kept
    assert tree["calls"][0][1].endswith("_atspi_glance.py")


def test_a_part_cut_short_or_unknown_is_not_kept(tree):
    tree["out"] = [helper({"windows": ["w1", True], "front": ["f1", False], "shell": ["", True], "pixels": ["x", True]})]
    assert D.glance().parts == {"windows": "w1"}


@pytest.mark.parametrize("out", ["", "not json", helper({}, ok=False), json.dumps({"ok": False, "error": "no bus"}),
                                 subprocess.TimeoutExpired("python3", 1), OSError("gone")])
def test_nothing_readable_is_no_glance_at_all(tree, out):
    tree["out"] = [out]
    assert D.glance() is None  # the focus extension is not loaded either: unknown, not "unchanged"


def test_off_switch_and_other_systems_read_no_tree(tree, monkeypatch):
    tree["out"] = [helper({"windows": ["w1", True]})]
    monkeypatch.setenv("SYRAX_SCREEN_TREE", "0")
    assert D.tree_glance() is None
    monkeypatch.delenv("SYRAX_SCREEN_TREE")
    monkeypatch.setattr(D, "WINDOWS", True)
    assert D.tree_glance() is None
    assert tree["calls"] == []


def test_tree_change_compares_only_the_parts_both_read():
    a = D.Fingerprint({"focus": "1", "windows": "2", "shell": "3"})
    assert D.tree_change(a, D.Fingerprint({"focus": "1", "windows": "2", "shell": "3"})) == []
    assert D.tree_change(a, D.Fingerprint({"focus": "1", "windows": "9"})) == ["windows"]
    assert D.tree_change(a, D.Fingerprint({"front": "7"})) is None  # nothing in common: unknown
    assert D.tree_change(a, None) is None
    assert D.screen_change(a, a) is None  # a Fingerprint is no image


def test_the_no_change_line_never_stands_for_no_outcome():
    line = D.tree_change_note([])
    assert line.startswith(" No change was seen in the windows")
    assert not claims.SCREEN_UNCHANGED.search(line)
    assert D.tree_change_note(None) == ""
    assert D.tree_change_note(["shell"]) == (" The screen changed: a GNOME menu, dialog, notification or the overview "
                                             "appeared or went away (seen in the accessibility tree, without a screenshot).")


@pytest.fixture
def hands(monkeypatch):
    """The desktop tool on Linux with faked hands, front window and glances."""
    state = {"shots": [], "done": []}
    monkeypatch.setattr(D, "WINDOWS", False)
    monkeypatch.setattr(D, "SCREEN_WAIT_S", 0)
    monkeypatch.setattr(D, "_gnome_front_read", lambda: ("'Notes' (gnome-text-editor)", ""))
    fake = types.SimpleNamespace(click=lambda where, how="left", b=None: state["done"].append(where)
                                 or f"Left-clicked at {where}.")
    monkeypatch.setattr(D, "_hands_module", lambda: fake)
    monkeypatch.setattr(D, "glance", lambda timeout=D.SCREEN_GLANCE_S: state["shots"].pop(0) if state["shots"] else None)
    return state


def act(action, **kw):
    return asyncio.run(D.DesktopControl().execute(action=action, **kw))


def test_a_click_that_opened_a_menu_says_so(hands):
    hands["shots"] = [D.Fingerprint({"shell": "a", "windows": "w"}), D.Fingerprint({"shell": "b", "windows": "w"})]
    out = act("click", target="412,630").output
    assert out.startswith("Left-clicked at 412,630.")
    assert out.endswith(" The screen changed: a GNOME menu, dialog, notification or the overview appeared or went away "
                        "(seen in the accessibility tree, without a screenshot).")
    assert claims.seen_acting("desktop", {"action": "click"}, out, {"desktop", "write"}) == {"desktop", "write"}


def test_a_click_the_tree_did_not_see_is_still_an_act(hands):
    same = {"focus": "f", "windows": "w", "shell": "s"}
    hands["shots"] = [D.Fingerprint(same), D.Fingerprint(same)]
    out = act("click", target="412,630").output
    assert D.TREE_NO_CHANGE_LINE in out
    assert claims.seen_acting("desktop", {"action": "click"}, out, {"desktop", "write"}) == {"desktop", "write"}


@pytest.mark.parametrize("after", [None, D.Fingerprint({"front": "x"})])
def test_an_after_glance_that_failed_or_shares_nothing_says_nothing(hands, after):
    hands["shots"] = [D.Fingerprint({"windows": "w"}), after]
    out = act("click", target="412,630").output
    assert "screen" not in out and "No change" not in out
    assert hands["done"] == ["412,630"]
