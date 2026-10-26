"""Click what it sees (feature catalog: click_by_sight): find a control or some words on the screen, then click their centre.

Two ways to look, both built into Windows, so there is no new dependency
(sight.ps1 runs in Windows PowerShell):
1. UI Automation: the names of controls, in the foreground window first and
   then on the whole desktop. It gives exact places for buttons, menus, links,
   tabs and list items.
2. OCR (Windows.Media.Ocr) of the primary screen, when no control carries the
   words well. It covers web pages, canvases and pictures of text.

Only the primary screen is searched, because wininput clicks there. Places are
scaled to the click's own coordinates, so display scaling cannot shift them.
SYRAX's own window is skipped as the foreground. When two places match equally
well nothing is clicked: the candidates come back, each naming the window it
lies in (and which one is in front), so the brain can choose and use click x,y.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

SCRIPT = Path(__file__).with_name("sight.ps1")
CLICKABLE = {"Button", "SplitButton", "MenuItem", "Hyperlink", "ListItem", "TabItem", "TreeItem",
             "CheckBox", "RadioButton", "ComboBox", "DataItem"}
MAX_NAME = 120  # longer "names" are documents or paragraphs, not something to click
STRONG = 60  # a control match this good means no OCR is needed
TIMEOUT_S = 40


@dataclass
class Spot:
    x: int
    y: int
    label: str
    how: str
    score: int
    window: str = ""  # the window it lies in; named only for a tie (in_windows)
    own: bool = False  # it lies in SYRAX's own window (winctl.is_own): never clicked

    def say(self) -> str:
        return f"{self.x},{self.y} {self.label} ({self.how})" + (f" in {self.window}" if self.window else "")


def norm(s: str) -> str:
    s = re.sub(r"[^\w\s]", " ", (s or "").replace("&", "").casefold())
    return " ".join(s.split())


def score_name(want: str, name: str) -> int:
    w, n = norm(want), norm(name)
    if not w or not n or len(name) > MAX_NAME:
        return 0
    if n == w:
        return 100
    if re.match(rf"{re.escape(w)}\b", n):
        return 80
    if re.search(rf"\b{re.escape(w)}\b", n):
        return 60
    if w in n:
        return 40
    if len(n) >= 3 and re.search(rf"\b{re.escape(n)}\b", w):
        return 30  # the control's name is part of what was asked ("the save button" ~ "Save")
    return 0


def from_uia(want: str, hits: List[dict]) -> List[Spot]:
    out = []
    for h in hits:
        s = score_name(want, str(h.get("name") or ""))
        if s:
            s += (10 if h.get("type") in CLICKABLE else 0) + (5 if h.get("fg") else 0)
            name = " ".join(str(h["name"]).split())[:60]
            out.append(Spot(int(h["x"]), int(h["y"]), f'{h.get("type") or "control"} "{name}"', "UI Automation", s))
    return out


def from_ocr(want: str, words: List[dict]) -> List[Spot]:
    target = norm(want).split()
    if not target:
        return []
    lines: Dict[int, List[dict]] = defaultdict(list)
    for w in words:
        if norm(str(w.get("text") or "")):
            lines[int(w.get("line") or 0)].append(w)
    out = []
    for ws in lines.values():
        toks = [norm(str(w["text"])) for w in ws]
        for i in range(len(ws) - len(target) + 1):
            if toks[i:i + len(target)] != target:
                continue
            run = ws[i:i + len(target)]
            x0, y0 = min(w["x"] for w in run), min(w["y"] for w in run)
            x1, y1 = max(w["x"] + w["w"] for w in run), max(w["y"] + w["h"] for w in run)
            line = " ".join(str(w["text"]) for w in ws)[:60]
            out.append(Spot((x0 + x1) // 2, (y0 + y1) // 2, f'text "{line}"', "OCR", 90 if len(toks) == len(target) else 70))
    return out


def place(spots: List[Spot], seen: Tuple[int, int], target: Tuple[int, int]) -> List[Spot]:
    """Keep the primary screen and scale from the looker's pixels to the clicker's."""
    sw, sh = seen
    tw, th = target
    out = []
    for s in spots:
        if 0 <= s.x < sw and 0 <= s.y < sh:
            out.append(Spot(round(s.x * tw / sw), round(s.y * th / sh), s.label, s.how, s.score))
    return out


def choose(spots: List[Spot]) -> Tuple[Optional[Spot], List[Spot]]:
    """The one best place, or None when several are equally good (or none)."""
    ranked = sorted(spots, key=lambda s: -s.score)
    if not ranked:
        return None, []
    distinct: List[Spot] = []
    for s in (s for s in ranked if s.score == ranked[0].score):
        if all(abs(s.x - d.x) > 8 or abs(s.y - d.y) > 8 for d in distinct):
            distinct.append(s)
    return (distinct[0] if len(distinct) == 1 else None), ranked[:6]


def window_words(w: Optional[dict]) -> str:
    """How a candidate's window is named: 'window "WhatsApp" (WhatsApp.exe, in front)'; '' when unknown.
    A title that looks private is masked exactly as presence.redact masks it."""
    from syrax.presence import redact

    if not w:
        return ""
    title = " ".join(str(w.get("title") or "").split())
    process = " ".join(str(w.get("process") or "").split())[:60]
    if not title and not process:
        return ""
    shown = redact(title) if title else ""
    head = (f'window "{shown}"' if shown == title[:80] else f"window {shown}") if title else "a window"
    notes = [n for n in (process, "in front" if w.get("front") else "") if n]
    return head + (f" ({', '.join(notes)})" if notes else "")


def in_windows(spots: List[Spot], reader: Optional[Callable[[int, int], Optional[dict]]] = None) -> List[Spot]:
    """A tie's candidates, each naming the window it lies in and marking the one in front.

    Live 2026-10-25: "send message to bro bhi" found "bro bhi" in two places equally well; the
    candidates were bare x,y and the brain clicked the first one blindly. This only adds words:
    nothing is clicked or focused, and a window that cannot be read leaves its candidate as it was.
    """
    from syrax.winctl import is_own

    if reader is None:
        from syrax.winctl import window_at as reader
    out = []
    for s in spots:
        try:
            w = reader(s.x, s.y)
            words, own = window_words(w), is_own(w)
        except Exception:
            words, own = "", False
        out.append(replace(s, window=words, own=s.own or own))
    return out


def outside_own(spots: List[Spot], reader: Optional[Callable[[int, int], Optional[dict]]] = None) -> Tuple[List[Spot], List[Spot]]:
    """(the places outside SYRAX's own windows, as found; the places inside them, named and marked own).

    Live 2026-10-25 "send message to bro bhi" with "SYRAX - Google Chrome" in front: OCR found the words only in
    SYRAX's own chat ("send message to bro bhi", "desktop bro bhi"), click_text clicked there, typed "hello" into
    SYRAX's own page and the answer said "Message sent". A window that cannot be read keeps its place."""
    named = in_windows(spots, reader)
    return [s for s, n in zip(spots, named) if not n.own], [n for n in named if n.own]


def look(mode: str, text: str, hwnd: int = 0) -> dict:
    env = {**os.environ, "SYRAX_SIGHT_MODE": mode, "SYRAX_SIGHT_TEXT": text, "SYRAX_SIGHT_HWND": str(hwnd)}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    p = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT)],
                       capture_output=True, timeout=TIMEOUT_S, env=env, creationflags=flags)
    out = p.stdout.decode("utf-8", errors="replace").strip()
    if p.returncode != 0 or not out:
        raise RuntimeError(f"looking at the screen ({mode}) failed: {p.stderr.decode('utf-8', errors='replace').strip()[-300:]}")
    return json.loads(out, strict=False)  # control names may carry tabs and newlines


def foreground() -> int:
    """The foreground window, unless it is SYRAX's own interface."""
    if sys.platform != "win32":
        return 0
    import ctypes

    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return 0 if "SYRAX" in buf.value else int(hwnd or 0)


def find(text: str, screen: Tuple[int, int], looker: Optional[Callable[..., dict]] = None,
         hwnd: Optional[int] = None, reader: Optional[Callable[[int, int], Optional[dict]]] = None
         ) -> Tuple[Optional[Spot], List[Spot]]:
    """Look with UI Automation, then OCR if no control matches well; `screen` is the clicker's screen size.

    A live look (no looker given), or one given a window reader, drops the places inside SYRAX's own windows
    (outside_own) before choosing; when every place was there, nothing is chosen and those places come back
    marked own. A given looker without a reader is a recorded screen: no live window is read for it."""
    mine = looker is None or reader is not None
    looker = looker or look
    own: List[Spot] = []

    def outside(found: List[Spot]) -> List[Spot]:
        if not mine or not found:
            return found
        kept, dropped = outside_own(found, reader)
        own.extend(dropped)
        return kept

    seen = looker("uia", text, foreground() if hwnd is None else hwnd)
    spots = outside(place(from_uia(text, seen.get("hits") or []), tuple(seen["screen"]), screen))
    if not spots or max(s.score for s in spots) < STRONG:
        read = looker("ocr", text, 0)
        spots += outside(place(from_ocr(text, read.get("hits") or []), tuple(read["screen"]), screen))
    if not spots and own:
        return None, sorted(own, key=lambda s: -s.score)[:6]
    return choose(spots)
