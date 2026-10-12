"""Click what it sees (feature catalog: click_by_sight): words are matched to
controls (UI Automation) or to read text (OCR), the primary screen is scaled
to the clicker's pixels, a tie clicks nothing, and the desktop actions use it.
The looker is faked (hits copied from a live screen on 2026-10-12): no
PowerShell runs and nothing is clicked here."""

import asyncio

from syrax import permissions, sight, wininput
from syrax.desktop import DesktopControl

START = [{"name": "Start", "type": "Button", "x": 24, "y": 276, "w": 48, "h": 45, "fg": False},
         {"name": "Start", "type": "Button", "x": -1896, "y": 228, "w": 48, "h": 45, "fg": False}]
TABS = [{"name": "Tab search", "type": "Button", "x": 68, "y": 20, "w": 30, "h": 30, "fg": True},
        {"name": "architecture - Google Search", "type": "TabItem", "x": 1104, "y": 20, "w": 200, "h": 30, "fg": True}]
WORDS = [{"text": "File", "line": 1, "x": 10, "y": 10, "w": 20, "h": 10},
         {"text": "Save", "line": 2, "x": 100, "y": 200, "w": 30, "h": 10}, {"text": "as", "line": 2, "x": 134, "y": 200, "w": 12, "h": 10},
         {"text": "Save", "line": 3, "x": 300, "y": 400, "w": 30, "h": 10}]


def looker(uia=(), ocr=(), screen=(1920, 1080), calls=None):
    def look(mode, text, hwnd=0):
        if calls is not None:
            calls.append((mode, text, hwnd))
        return {"screen": list(screen), "hits": list(uia if mode == "uia" else ocr)}
    return look


def test_how_well_a_name_matches_the_words():
    assert sight.score_name("save", "Save") == 100 and sight.score_name("Save", "Save as...") == 80
    assert sight.score_name("search", "Tab search") == 60 and sight.score_name("sea", "Research") == 40
    assert sight.score_name("the save button", "Save") == 30 and sight.score_name("save", "Open") == 0
    assert sight.score_name("save", "&Save") == 100 and sight.score_name("start", "x" * 200 + " start") == 0


def test_the_off_screen_twin_is_dropped_and_a_control_match_needs_no_ocr():
    calls = []
    spot, seen = sight.find("Start", (1920, 1080), looker(START, calls=calls), hwnd=7)
    assert (spot.x, spot.y, spot.how) == (24, 276, "UI Automation") and len(seen) == 1
    assert calls == [("uia", "Start", 7)]  # strong control match: the screen is not read


def test_ocr_reads_the_screen_when_no_control_matches_and_scaling_follows_the_clicker():
    calls = []
    spot, _ = sight.find("save as", (1536, 864), looker(ocr=WORDS, calls=calls), hwnd=0)
    assert [c[0] for c in calls] == ["uia", "ocr"] and spot.how == "OCR" and spot.label == 'text "Save as"'
    assert (spot.x, spot.y) == (round(123 * 0.8), round(205 * 0.8))  # 125 % scaling: 1920 seen, 1536 clicked


def test_a_tie_clicks_nothing_and_returns_the_candidates():
    spot, seen = sight.find("search", (1920, 1080), looker(TABS), hwnd=0)
    assert spot is None and [s.x for s in seen] == [68, 1104]
    spot, seen = sight.find("save", (1920, 1080), looker(ocr=WORDS), hwnd=0)
    assert spot is not None and (spot.x, spot.y) == (315, 405) and spot.score == 90  # the line that is only "Save"
    assert sight.choose([]) == (None, [])


def test_click_text_clicks_the_one_place_and_find_text_only_reports(monkeypatch):
    clicks = []
    monkeypatch.setattr(sight, "find", lambda text, screen: (sight.Spot(24, 276, 'Button "Start"', "UI Automation", 110),
                                                            [sight.Spot(24, 276, 'Button "Start"', "UI Automation", 110)]))
    monkeypatch.setattr(wininput, "backend", lambda: type("B", (), {"screen": lambda self: (1920, 1080)})())
    monkeypatch.setattr(wininput, "click", lambda where, how="left", b=None: clicks.append((where, how)) or f"Left-clicked at {where}.")
    out = asyncio.run(DesktopControl().execute(action="click_text", target="Start"))
    assert out.error is None and out.output == 'Left-clicked at 24,276. That is Button "Start", found by UI Automation.'
    found = asyncio.run(DesktopControl().execute(action="find_text", target="Start"))
    assert found.output.startswith('Best: 24,276 Button "Start" (UI Automation).') and clicks == [("24,276", "left")]


def test_a_tie_or_nothing_is_an_error_and_nothing_is_clicked(monkeypatch):
    clicks = []
    monkeypatch.setattr(wininput, "backend", lambda: type("B", (), {"screen": lambda self: (1920, 1080)})())
    monkeypatch.setattr(wininput, "click", lambda *a, **k: clicks.append(a))
    two = [sight.Spot(68, 20, 'Button "Tab search"', "UI Automation", 70), sight.Spot(1104, 20, 'TabItem "Search"', "UI Automation", 70)]
    monkeypatch.setattr(sight, "find", lambda text, screen: (None, two))
    out = asyncio.run(DesktopControl().execute(action="click_text", target="search"))
    assert "matches several places equally well; nothing was clicked" in out.error and "68,20" in out.error
    monkeypatch.setattr(sight, "find", lambda text, screen: (None, []))
    assert "Nothing on the primary screen reads" in asyncio.run(DesktopControl().execute(action="click_text", target="zzz")).error
    assert "need the words" in asyncio.run(DesktopControl().execute(action="click_text", target=" ")).error
    assert clicks == []


def test_clicking_is_system_and_finding_only_reads():
    assert permissions.classify("desktop", {"action": "click_text", "target": "Save"}).level == permissions.SYSTEM
    assert permissions.classify("desktop", {"action": "find_text", "target": "Save"}).level == permissions.READ_ONLY
    d = permissions.classify("desktop", {"action": "click_text", "target": "Save"})
    assert permissions.decide(d, "autonomous", "tidy up").action == "refuse"
