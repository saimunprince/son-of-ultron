"""Host check: try SYRAX's desktop actions for real on this computer and compare with what hostprofile predicts.

The owner (2026-11-05): SYRAX should run right on every Linux, every Windows and other systems. Tests on one PC
cannot show that; this check runs on the new PC itself:

    python syrax.py --hostcheck                 safe actions only (reads, a notification, a screenshot)
    python syrax.py --hostcheck hands camera    also press Shift once and take one webcam photo

It writes docs/hostchecks/<os>-<desktop>-<display>-<date>.md. The report keeps no private data: no clipboard text,
window titles, app names or pictures, only whether each action worked and the error text (home folder as ~).
A MISMATCH means hostprofile said one thing and the action did the other: fix hostprofile.py or desktop.py.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import os
import re
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

from syrax import hostprofile

say = print  # a command-line tool: its output is the point
REPORT_DIR = Path(__file__).resolve().parents[2] / "docs" / "hostchecks"
MARK = "SYRAX host check"
# Actions the check never runs: each changes the screen, the files or the session.
NOT_TRIED = {"open": "opens a window", "launch_app": "starts an app", "type_text": "types into the window in front",
             "click": "clicks the mouse", "click_text": "clicks the mouse", "lock_screen": "locks the screen",
             "display_off": "turns the display off", "trash": "moves a file to the trash",
             "view_video": "needs a video file"}


def private(text: str) -> str:
    """Error text fit for a public report: the home folder as ~, the user name gone, one short line."""
    home = str(Path.home())
    text = (text or "").replace(home, "~").replace(home.replace("\\", "/"), "~")
    user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    if len(user) > 2:
        text = re.sub(re.escape(user), "<user>", text, flags=re.I)
    return " ".join(text.split())[:200]


def black(png: bytes) -> Optional[bool]:
    """Whether a screenshot is (almost) all black, as an X server without a session or a locked screen gives;
    None when Pillow cannot read it."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(png)).convert("L")
        img.thumbnail((320, 320))
        return img.getextrema()[1] < 16
    except Exception:
        return None


def verdict(predicted: str, worked: Optional[bool]) -> str:
    """OK / FAILS (both agree it cannot) / MISMATCH / NOT TRIED."""
    if worked is None:
        return "NOT TRIED"
    said_yes = predicted.startswith("yes")
    if said_yes and worked:
        return "OK"
    if not said_yes and not worked:
        return "NO (as predicted)"
    return "MISMATCH"


async def run_checks(extras: Tuple[str, ...] = ()) -> List[dict]:
    from syrax.desktop import DesktopControl

    tool = DesktopControl()
    acts = hostprofile.profile()["actions"]
    rows: List[dict] = []

    async def go(key: str, action: str, note: str = "", **kw) -> Optional[object]:
        t0 = time.monotonic()
        try:
            res = await asyncio.wait_for(tool.execute(action, **kw), timeout=60)
            err = res.error
        except Exception as e:  # a crash is a result too
            res, err = None, f"{type(e).__name__}: {e}"
        if err and key == "phone" and "No Android phone is connected" in str(err):
            err, note = "", "adb works; no phone is connected"
        row = {"action": key, "predicted": acts.get(key, "yes"), "worked": not err,
               "detail": private(str(err)) if err else note, "ms": int((time.monotonic() - t0) * 1000)}
        rows.append(row)
        return None if err else res

    await go("system_info", "system_info")
    await go("list_apps", "list_apps", target="")
    await go("volume", "volume", value="get")
    await go("media", "media", value="status")
    await go("notify", "notify", value=MARK)
    await go("dark_mode", "dark_mode", value="get")
    await go("window", "window", value="list")
    await go("find_text", "find_text", target="SYRAX")
    await go("phone", "phone", value="status")

    shot = await go("screenshot", "screenshot")
    if shot is not None:
        row = rows[-1]
        is_black = black(base64.b64decode(shot.base64_image or ""))
        if is_black:
            row["worked"], row["detail"] = False, "the picture is all black (no real session, or a locked screen)"
        try:
            path = re.search(r"saved to (.+)$", shot.output or "")
            if path:
                Path(path.group(1).strip()).unlink(missing_ok=True)
        except OSError:
            pass

    before = await tool.execute("clipboard_get")
    sent = f"{MARK} {int(time.time())}"
    put = await tool.execute("clipboard_set", value=sent)
    got = await tool.execute("clipboard_get")
    ok = not put.error and not got.error and (got.output or "").strip() == sent
    detail = "" if ok else private(put.error or got.error or "read back something else")
    if not before.error:  # give the human's clipboard back
        old = before.output or ""
        await tool.execute("clipboard_set", value="" if old == "(clipboard is empty)" else old)
    rows.append({"action": "clipboard", "predicted": acts.get("clipboard", "yes"), "worked": ok,
                 "detail": detail, "ms": 0})

    if "hands" in extras:
        await go("hotkey", "hotkey", "pressed Shift once", value="shift")
    if "camera" in extras:
        await go("camera", "camera")
    tried = {r["action"] for r in rows}
    for key, why in NOT_TRIED.items():
        rows.append({"action": key, "predicted": acts.get(key, "yes"), "worked": None, "detail": f"not tried: {why}", "ms": 0})
    for key in ("hotkey", "camera"):
        if key not in tried:
            flag = "hands" if key == "hotkey" else "camera"
            rows.append({"action": key, "predicted": acts.get(key, "yes"), "worked": None,
                         "detail": f"not tried (add: --hostcheck {flag})", "ms": 0})
    for r in rows:
        r["verdict"] = verdict(r["predicted"], r["worked"])
    return rows


def report(p: dict, rows: List[dict], when: Optional[str] = None) -> str:
    when = when or time.strftime("%Y-%m-%d %H:%M")
    bad = [r for r in rows if r["verdict"] == "MISMATCH"]
    tools = ", ".join(t for t, ok in sorted(p["tools"].items()) if ok) or "none"
    lines = [f"# Host check: {p['name']}", "",
             f"- When: {when}",
             f"- System: {p['name']}, kernel {p['kernel']}, {p['arch']}",
             f"- Desktop: {p['desktop']} on {p['display']}",
             f"- Helper programs found: {tools}",
             f"- Python: {sys.version.split()[0]}",
             f"- Result: {'ALL AS PREDICTED' if not bad else f'{len(bad)} MISMATCH'}", "",
             "| Action | Predicted | Result | Detail |", "|---|---|---|---|"]
    for r in rows:
        detail = r["detail"].replace("|", "/")
        lines.append(f"| {r['action']} | {r['predicted'].replace('|', '/')} | {r['verdict']} | {detail} |")
    lines += ["", "A MISMATCH means hostprofile.py predicted one thing and the action did the other.", ""]
    return "\n".join(lines)


def slug(*parts: str) -> str:
    return "-".join(re.sub(r"[^a-z0-9]+", "", s.lower()) or "x" for s in parts)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("extras", nargs="*", choices=("hands", "camera"), help="also press Shift once / take one webcam photo")
    ap.add_argument("--out", type=Path, default=REPORT_DIR)
    a = ap.parse_args(argv)
    p = hostprofile.profile()
    say(hostprofile.summary(p), flush=True)
    rows = asyncio.run(run_checks(tuple(a.extras)))
    text = report(p, rows)
    a.out.mkdir(parents=True, exist_ok=True)
    path = a.out / f"{slug(p['os'], p['desktop'], p['display'])}-{time.strftime('%Y%m%d')}.md"
    path.write_text(text, encoding="utf-8", newline="\n")
    for r in rows:
        say(f"  {r['verdict']:<18} {r['action']:<12} {r['detail']}")
    say(f"report: {path}")
    say("Share it: git add docs/hostchecks && git commit -m 'hostcheck' && git push  (or send the file)")
    return 1 if any(r["verdict"] == "MISMATCH" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
