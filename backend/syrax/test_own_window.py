"""SYRAX never types, presses keys or clicks into its own window.

Live 2026-10-25 all 12 desktop calls ran with "SYRAX - Google Chrome" in front (presence.window): the owner types
requests into SYRAX's web UI. "send message to bro bhi" ran click_text, whose OCR found the words only in SYRAX's
own chat ("send message to bro bhi" at 1724,902, "desktop bro bhi" at 1877,159); it clicked 1877,159, typed "hello",
pressed Enter inside SYRAX's own page and answered "Message sent". The php2shell text went into SYRAX's window twice
and alt+f4 for Notepad was pressed at it. The window reader, the screen and the hands are faked here: nothing is
typed, pressed, clicked or read from the real screen.
"""

import asyncio

import pytest

from syrax import desktop as D
from syrax import sight, winctl, wininput

CHROME = {"title": "SYRAX - Google Chrome", "process": "chrome.exe", "pid": 3}
HUD = {"title": "SYRAX", "process": "electron.exe", "pid": 4}
TELEGRAM = {"title": "bro bhi – Telegram", "process": "Telegram.exe", "pid": 7}
REFUSAL = ("the window in front is SYRAX's own ({}): bring the target to the front first with desktop window focus "
           "<part of its title> or launch_app, then try again")


@pytest.fixture
def hands(monkeypatch):
    state = {"front": CHROME, "done": []}
    monkeypatch.setattr(D, "WINDOWS", True)
    monkeypatch.setattr(winctl, "foreground", lambda: state["front"])
    monkeypatch.setattr(wininput, "type_text", lambda text, b=None, pause=0.004: state["done"].append(("type", text))
                        or f"Typed {len(text)} characters into the focused window.")
    monkeypatch.setattr(wininput, "hotkey", lambda spec, b=None: state["done"].append(("keys", spec)) or f"Pressed {spec}.")
    monkeypatch.setattr(wininput, "click", lambda where, how="left", b=None: state["done"].append(("click", where))
                        or f"Left-clicked at {where}.")
    monkeypatch.setattr(wininput, "backend", lambda: type("B", (), {"screen": lambda self: (1920, 1080)})())
    return state


def act(action, **kw):
    return asyncio.run(D.DesktopControl().execute(action=action, **kw))


@pytest.mark.parametrize("w", [CHROME, HUD, {"title": "SYRAX", "process": "msedge.exe"}, {"title": "Chat - SYRAX", "process": "firefox.exe"},
                               {"title": "SYRAX - Google Chrome", "process": ""}, {"title": " SYRAX ", "process": ""}])
def test_syrax_own_windows_are_recognised(w):
    assert winctl.is_own(w)


@pytest.mark.parametrize("w", [None, {}, TELEGRAM, {"title": "SYRAX", "process": "explorer.exe"},
                               {"title": "SYRAX_STATUS.md - son-of-ultron - Visual Studio Code", "process": "Code.exe"},
                               {"title": "Syrax - A Wiki of Ice and Fire - Google Chrome", "process": "chrome.exe"},
                               {"title": "SYRAX - Notepad", "process": ""}, {"title": "SYRAX browser check - Google Chrome", "process": "chrome.exe"}])
def test_other_windows_are_not_syrax(w):
    assert not winctl.is_own(w)


@pytest.mark.parametrize("front", [CHROME, HUD])
def test_text_keys_and_clicks_are_refused_with_syrax_in_front(hands, front):
    hands["front"] = front
    assert act("type_text", value="hello").error == REFUSAL.format(front["title"])
    assert act("hotkey", value="alt+f4").error == REFUSAL.format(front["title"])
    assert act("click", target="1877,159").error == REFUSAL.format(front["title"])
    assert hands["done"] == []


def test_another_window_in_front_still_gets_them(hands):
    hands["front"] = TELEGRAM
    assert act("type_text", value="hello").output == "Typed 5 characters into the focused window. In front now: 'bro bhi – Telegram' (Telegram.exe)."
    assert act("hotkey", value="enter").output == "Pressed enter. In front now: 'bro bhi – Telegram' (Telegram.exe)."
    assert act("click", target="412,630").output == "Left-clicked at 412,630. In front now: 'bro bhi – Telegram' (Telegram.exe)."
    hands["front"] = {"title": "SYRAX", "process": "explorer.exe"}  # a folder named SYRAX is not SYRAX
    assert act("type_text", value="x").error is None
    assert hands["done"] == [("type", "hello"), ("keys", "enter"), ("click", "412,630"), ("type", "x")]


def at(x, y):
    """SYRAX's page fills the right of the screen, Telegram the left."""
    return CHROME | {"front": True} if x >= 1000 else TELEGRAM | {"front": False}


def test_a_tie_drops_syrax_own_place_and_clicks_the_one_left(hands, monkeypatch):
    tie = [sight.Spot(1877, 159, 'text "desktop bro bhi"', "OCR", 70), sight.Spot(412, 630, 'text "chat bro bhi"', "OCR", 70)]
    monkeypatch.setattr(sight, "find", lambda text, screen: (None, tie))
    monkeypatch.setattr(winctl, "window_at", at)
    out = act("click_text", target="bro bhi")
    assert out.output == ("Left-clicked at 412,630. That is text \"chat bro bhi\", found by OCR. "
                          "Skipped 1 place(s) in SYRAX's own window.")
    assert hands["done"] == [("click", "412,630")]


def test_a_tie_left_after_dropping_is_still_a_tie(hands, monkeypatch):
    tie = [sight.Spot(1877, 159, 'text "bro bhi"', "OCR", 90), sight.Spot(412, 630, 'text "bro bhi"', "OCR", 90),
           sight.Spot(300, 200, 'text "bro bhi"', "OCR", 90)]
    monkeypatch.setattr(sight, "find", lambda text, screen: (None, tie))
    monkeypatch.setattr(winctl, "window_at", at)
    out = act("click_text", target="bro bhi")
    assert out.error.startswith('"bro bhi" matches several places equally well; nothing was clicked.')
    assert "1877,159" not in out.error and "412,630" in out.error and "300,200" in out.error
    assert out.error.endswith("Skipped 1 place(s) in SYRAX's own window.") and hands["done"] == []


def ocr_line(line, words, y):
    """OCR words on one line, 30 px apart, each 20x18."""
    return [{"text": t, "line": line, "x": x0, "y": y, "w": 20, "h": 18} for t, x0 in words]


INCIDENT = (ocr_line(1, [("send", 1600), ("message", 1630), ("to", 1660), ("bro", 1714), ("bhi", 1724)], 893)
            + ocr_line(2, [("desktop", 1820), ("bro", 1850), ("bhi", 1880)], 150))


def live_screen(monkeypatch, words):
    """sight.find's own live path, fed a recorded screen: UI Automation finds nothing, OCR finds `words`."""
    calls = []

    def look(mode, text, hwnd=0):
        calls.append(mode)
        return {"hits": words if mode == "ocr" else [], "screen": [1920, 1080]}

    monkeypatch.setattr(sight, "look", look)
    monkeypatch.setattr(sight, "foreground", lambda: 0)
    monkeypatch.setattr(winctl, "window_at", at)
    return calls


def test_the_incident_words_only_in_syrax_chat_are_never_clicked(hands, monkeypatch):
    live_screen(monkeypatch, INCIDENT)
    out = act("click_text", target="bro bhi")
    assert out.error == ('The words "bro bhi" were found only in SYRAX\'s own window (window "SYRAX - Google Chrome" '
                         '(chrome.exe, in front)): that is SYRAX\'s own chat, not the target. Nothing was clicked. Bring the '
                         "target to the front first with desktop window focus <part of its title> or launch_app, then try again.")
    found = act("find_text", target="bro bhi")
    assert found.output.startswith('The words "bro bhi" were found only in SYRAX\'s own window')
    assert found.output.endswith("Nothing else on the primary screen reads it.")
    assert hands["done"] == []


def test_live_the_place_outside_syrax_is_the_one_clicked(hands, monkeypatch):
    live_screen(monkeypatch, INCIDENT + ocr_line(3, [("chat", 380), ("bro", 410), ("bhi", 440)], 621))
    out = act("click_text", target="bro bhi")
    assert out.output == 'Left-clicked at 435,630. That is text "chat bro bhi", found by OCR.'
    assert hands["done"] == [("click", "435,630")]
    found = act("find_text", target="bro bhi")
    assert found.output == 'Best: 435,630 text "chat bro bhi" (OCR). Seen: 435,630 text "chat bro bhi" (OCR)'


def test_find_reads_windows_only_live_or_with_a_reader():
    def looker(mode, text, hwnd=0):
        return {"hits": INCIDENT if mode == "ocr" else [], "screen": [1920, 1080]}

    spot, seen = sight.find("desktop bro bhi", (1920, 1080), looker, hwnd=0)  # a recorded screen: no window is read
    assert spot is not None and (spot.x, spot.y) == (1860, 159) and not spot.own
    spot, seen = sight.find("desktop bro bhi", (1920, 1080), looker, hwnd=0, reader=at)
    assert spot is None and [(s.x, s.y, s.own) for s in seen] == [(1860, 159, True)]
    assert seen[0].window == 'window "SYRAX - Google Chrome" (chrome.exe, in front)'


def test_an_unreadable_window_keeps_its_place():
    spots = [sight.Spot(1, 2, "a", "OCR", 90)]

    def broken(x, y):
        raise OSError("no desktop")

    assert sight.outside_own(spots, broken) == (spots, [])
    assert sight.outside_own(spots, lambda x, y: None) == (spots, [])
