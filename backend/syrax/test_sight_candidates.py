"""A tie's candidates name their window (sight.in_windows, winctl.window_at).

Live 2026-10-25 the owner said "send message to bro bhi"; click_text found "bro bhi" in two places
equally well, the candidates were bare x,y, and the brain clicked the first one blindly. Now each
candidate names the top-level window it lies in, marks the one in front, and masks a title that
looks private as presence.redact does. The screen and the window reader are faked: nothing is
clicked and no real window or screen is read here.
"""

import asyncio

from syrax import sight, winctl, wininput
from syrax.desktop import DesktopControl

TIE = [sight.Spot(1877, 159, 'text "bro bhi"', "OCR", 90), sight.Spot(412, 630, 'text "bro bhi"', "OCR", 90)]
OLD = ('"bro bhi" matches several places equally well; nothing was clicked. Choose one and use click with its x,y: '
       '1877,159 text "bro bhi" (OCR); 412,630 text "bro bhi" (OCR)')


def windows(table, calls=None):
    def at(x, y):
        if calls is not None:
            calls.append((x, y))
        w = table[(x, y)]
        if isinstance(w, Exception):
            raise w
        return w
    return at


def fake_screen(monkeypatch, found, table):
    clicks, calls = [], []
    monkeypatch.setattr(sight, "find", lambda text, screen: found)
    monkeypatch.setattr(wininput, "backend", lambda: type("B", (), {"screen": lambda self: (1920, 1080)})())
    monkeypatch.setattr(wininput, "click", lambda *a, **k: clicks.append(a) or "Left-clicked.")
    monkeypatch.setattr(winctl, "window_at", windows(table, calls))
    return clicks, calls


def test_the_candidates_name_their_window_and_mark_the_one_in_front(monkeypatch):
    clicks, calls = fake_screen(monkeypatch, (None, TIE), {
        (1877, 159): {"title": "WhatsApp", "process": "WhatsApp.exe", "front": True},
        (412, 630): {"title": "notes.txt - Notepad", "process": "Notepad.exe", "front": False}})
    out = asyncio.run(DesktopControl().execute(action="click_text", target="bro bhi"))
    assert out.error == ('"bro bhi" matches several places equally well; nothing was clicked. Choose one and use click with its x,y: '
                         '1877,159 text "bro bhi" (OCR) in window "WhatsApp" (WhatsApp.exe, in front); '
                         '412,630 text "bro bhi" (OCR) in window "notes.txt - Notepad" (Notepad.exe)')
    found = asyncio.run(DesktopControl().execute(action="find_text", target="bro bhi"))
    assert found.output == ('Several places match equally well. Seen: '
                            '1877,159 text "bro bhi" (OCR) in window "WhatsApp" (WhatsApp.exe, in front); '
                            '412,630 text "bro bhi" (OCR) in window "notes.txt - Notepad" (Notepad.exe)')
    assert clicks == [] and sorted(calls) == sorted([(1877, 159), (412, 630)] * 2)


def test_a_title_that_looks_private_is_masked(monkeypatch):
    clicks, _ = fake_screen(monkeypatch, (None, TIE), {
        (1877, 159): {"title": "Inbox (3) - me@example.com - Gmail", "process": "chrome.exe", "front": True},
        (412, 630): {"title": "", "process": "WhatsApp.exe", "front": False}})
    out = asyncio.run(DesktopControl().execute(action="click_text", target="bro bhi"))
    assert out.error.endswith('1877,159 text "bro bhi" (OCR) in window [title not recorded: it looked private] (chrome.exe, in front); '
                              '412,630 text "bro bhi" (OCR) in a window (WhatsApp.exe)')
    assert "example.com" not in out.error and "Inbox" not in out.error and clicks == []


def test_a_window_that_cannot_be_read_leaves_the_old_message(monkeypatch):
    clicks, _ = fake_screen(monkeypatch, (None, TIE), {(1877, 159): OSError("no window"), (412, 630): None})
    assert asyncio.run(DesktopControl().execute(action="click_text", target="bro bhi")).error == OLD
    fake_screen(monkeypatch, (None, TIE), {(1877, 159): {}, (412, 630): {"title": " ", "process": "", "front": True}})
    assert asyncio.run(DesktopControl().execute(action="click_text", target="bro bhi")).error == OLD
    monkeypatch.setattr(sight, "in_windows", lambda spots: 1 / 0)  # even a broken namer cannot break the tie's answer
    assert asyncio.run(DesktopControl().execute(action="click_text", target="bro bhi")).error == OLD
    assert clicks == []


def test_one_best_place_reads_no_window_and_its_answer_is_unchanged(monkeypatch):
    best = sight.Spot(24, 276, 'Button "Start"', "UI Automation", 110)
    clicks, calls = fake_screen(monkeypatch, (best, [best]), {})
    out = asyncio.run(DesktopControl().execute(action="click_text", target="Start"))
    assert out.output == 'Left-clicked. That is Button "Start", found by UI Automation.' and calls == []
    found = asyncio.run(DesktopControl().execute(action="find_text", target="Start"))
    assert found.output == 'Best: 24,276 Button "Start" (UI Automation). Seen: 24,276 Button "Start" (UI Automation)' and calls == []


def test_in_windows_takes_a_reader_and_keeps_the_places():
    named = sight.in_windows(TIE, windows({(1877, 159): {"title": "WhatsApp", "process": "", "front": True},
                                           (412, 630): {"title": "x" * 200, "process": "Code.exe", "front": False}}))
    assert [(s.x, s.y, s.label, s.how, s.score) for s in named] == [(s.x, s.y, s.label, s.how, s.score) for s in TIE]
    assert named[0].window == 'window "WhatsApp" (in front)' and named[1].window == f'window "{"x" * 80}" (Code.exe)'
    assert [s.window for s in TIE] == ["", ""]  # the found places are not changed in place
    assert sight.window_words(None) == "" and sight.window_words({"front": True}) == ""
