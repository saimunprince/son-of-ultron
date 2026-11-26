"""A click, keys or typed text say whether the screen changed after them (idea from Mark-LVII, 2026-11-26).

The glances are faked here (desktop.glance): nothing reads the real screen, and the hands are fakes, so nothing is typed,
pressed or clicked.
"""

import asyncio

import pytest
from PIL import Image, ImageDraw

from syrax import claims, desktop as D
from syrax import sight, winctl, wininput

TELEGRAM = {"title": "bro bhi – Telegram", "process": "Telegram.exe", "pid": 7}
CHROME = {"title": "SYRAX - Google Chrome", "process": "chrome.exe", "pid": 3}


def gray(spots=()):
    """A small gray screen with white boxes at (x0, y0, x1, y1)."""
    img = Image.new("L", D.SCREEN_SIZE, 40)
    draw = ImageDraw.Draw(img)
    for box in spots:
        draw.rectangle(box, fill=255)
    return img


@pytest.fixture
def screen(monkeypatch):
    state = {"front": TELEGRAM, "done": [], "shots": [], "glances": 0}
    monkeypatch.setattr(D, "WINDOWS", True)
    monkeypatch.setattr(D, "SCREEN_WAIT_S", 0)
    monkeypatch.setattr(winctl, "foreground", lambda: state["front"])
    monkeypatch.setattr(wininput, "type_text", lambda text, b=None, pause=0.004: state["done"].append(("type", text))
                        or f"Typed {len(text)} characters into the focused window.")
    monkeypatch.setattr(wininput, "hotkey", lambda spec, b=None: state["done"].append(("keys", spec)) or f"Pressed {spec}.")
    monkeypatch.setattr(wininput, "click", lambda where, how="left", b=None: state["done"].append(("click", where))
                        or f"Left-clicked at {where}.")
    monkeypatch.setattr(wininput, "backend", lambda: type("B", (), {"screen": lambda self: (1920, 1080)})())

    def fake_glance(timeout=D.SCREEN_GLANCE_S):
        state["glances"] += 1
        shot = state["shots"].pop(0) if state["shots"] else None
        if isinstance(shot, Exception):
            raise shot
        return shot

    monkeypatch.setattr(D, "glance", fake_glance)
    return state


def act(action, **kw):
    return asyncio.run(D.DesktopControl().execute(action=action, **kw))


FRONT = " In front now: 'bro bhi – Telegram' (Telegram.exe)."


def test_a_dialog_that_opens_is_a_change(screen):
    screen["shots"] = [gray(), gray([(20, 20, 200, 120)])]
    out = act("click", target="412,630").output
    assert out.startswith("Left-clicked at 412,630." + FRONT + " The screen changed (")
    assert out.endswith("% of it).")
    assert D.screen_change(gray(), gray([(20, 20, 200, 120)])) > 0.4


def test_nothing_changed_is_said(screen):
    screen["shots"] = [gray([(5, 5, 9, 9)]), gray([(5, 5, 9, 9)])]
    assert act("hotkey", value="ctrl+s").output == "Pressed ctrl+s." + FRONT + " Nothing on the screen changed after this."


def test_a_blinking_cursor_or_clock_is_not_a_change(screen):
    # a cursor 1x8 and a clock digit 5x7 at 256x144: about 0.12 % of the pixels, under SCREEN_CHANGED_MIN (0.5 %)
    screen["shots"] = [gray(), gray([(100, 60, 100, 67), (240, 2, 244, 8)])]
    out = act("type_text", value="hello").output
    assert out == ("Typed 5 characters into the focused window." + FRONT + " Nothing on the screen changed after this, "
                   "beyond a tiny spot (under 0.5% of it, as small as a cursor, a clock or a checkbox).")
    assert claims.SCREEN_UNCHANGED.search(out)


def test_faint_noise_is_no_change_at_all():
    noisy = gray().point(lambda v: v + 10)  # compression or dimming: gray moves less than SCREEN_PIXEL_DELTA
    assert D.screen_change(gray(), noisy) == 0.0
    assert D.screen_change_note(0.0) == " Nothing on the screen changed after this."
    assert D.screen_change_note(0.005) == " The screen changed (0.5% of it)."
    assert D.screen_change_note(0.42) == " The screen changed (42% of it)."


@pytest.mark.parametrize("shots", [[None, None], [RuntimeError("no display")], [gray(), None], [gray(), RuntimeError("portal refused")]])
def test_a_capture_that_fails_says_nothing_and_never_fails_the_action(screen, shots):
    screen["shots"] = list(shots)
    assert act("click", target="412,630").output == "Left-clicked at 412,630." + FRONT
    assert screen["done"] == [("click", "412,630")]


def test_no_glance_on_the_real_screen_in_tests(monkeypatch):
    monkeypatch.undo()
    assert D.glance() is None  # SYRAX_NO_REAL_INPUT=1 (conftest)


def test_sizes_that_differ_cannot_be_compared():
    assert D.screen_change(gray(), Image.new("L", (10, 10))) is None
    assert D.screen_change(None, gray()) is None
    assert D.screen_change_note(None) == ""


def test_own_window_refusal_takes_no_glance(screen):
    screen["front"] = CHROME
    for action, kw in (("type_text", {"value": "hello"}), ("hotkey", {"value": "alt+f4"}), ("click", {"target": "1877,159"})):
        assert act(action, **kw).error.startswith("the window in front is SYRAX's own (SYRAX - Google Chrome)")
    assert screen["done"] == [] and screen["glances"] == 0


def test_click_text_says_whether_the_screen_changed(screen, monkeypatch):
    spot = sight.Spot(300, 400, "the Save button", "UI Automation", 100)

    async def found(self, target):
        return spot, [spot], []

    monkeypatch.setattr(D.DesktopControl, "_sight", found)
    screen["shots"] = [gray(), gray()]
    out = act("click_text", target="Save").output
    assert out.endswith("found by UI Automation. Nothing on the screen changed after this.")
    assert screen["done"] == [("click", "300,400")]


def test_a_click_that_changed_nothing_stands_for_no_outcome():
    cls = {"desktop", "write"}
    body = "Left-clicked at 412,630." + FRONT + " Nothing on the screen changed after this."
    assert claims.seen_acting("desktop", {"action": "click"}, body, cls) == {"write"}
    assert claims.seen_acting("desktop", {"action": "click"}, "Left-clicked at 1,2. The screen changed (3.1% of it).", cls) == cls
    assert claims.seen_acting("desktop", {"action": "volume"}, body, cls) == cls  # only the hands actions
    assert claims.seen_acting("python_execute", {"action": "click"}, body, cls) == cls
