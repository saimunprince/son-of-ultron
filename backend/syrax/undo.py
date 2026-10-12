"""Undo: "undo that" reverses SYRAX's own last reversible action.

Nothing new is stored: the history is a pure function of the tool calls the
journal already records. A successful call is reversible when its output says
what it replaced (screen brightness, wallpaper, dark mode) or when it edited a
file (the editor's undo_edit). A later call that is exactly its reverse marks
it undone.

The `undo` tool does not act. It tells the brain the newest actions not yet
undone and the exact call that reverses each, and the brain makes that call
through the normal path, so permissions and the journal treat it like any
other call. The editor keeps its undo history in memory, so a file edit made
before a restart cannot be undone this way, and a file sent to the Recycle Bin
is restored from the Recycle Bin.

From the feature catalog (undo); the idea came from the surveyed JARVIS
assistants, the code is SYRAX's own.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Callable, Dict, List, Optional

from pydantic import Field

from app.tool.base import BaseTool, ToolResult
from syrax.journal import Journal, get_journal

BRIGHTNESS = re.compile(r"Screen brightness (\d+)% -> (\d+)%")
WALLPAPER = re.compile(r"Wallpaper set to (.+?) \(it was (.+?); to undo")
THEME = re.compile(r"Windows switched from (light|dark) to (light|dark) mode")
EDITS = {"create", "str_replace", "insert"}
WINDOW = 3000  # how far back (journal events) "undo" looks


def _body(output: str) -> str:
    return re.sub(r"^Observed output of cmd `[^`]+` executed:\s*", "", str(output or ""))


def reverse_of(tool: str, args: Dict[str, Any], output: str) -> Optional[Dict[str, Any]]:
    """{label, reverse: {tool, args}} for a successful reversible call, else None."""
    a = args if isinstance(args, dict) else {}
    out = _body(output)
    if tool == "screen_brightness" and (m := BRIGHTNESS.search(out)):
        return {"label": f"screen brightness {m.group(1)}% -> {m.group(2)}%",
                "reverse": {"tool": "screen_brightness", "args": {"action": "set", "level": int(m.group(1))}}}
    if tool == "wallpaper" and (m := WALLPAPER.search(out)) and m.group(2) != "(none)":
        return {"label": f"wallpaper {m.group(2)} -> {m.group(1)}",
                "reverse": {"tool": "wallpaper", "args": {"action": "set", "path": m.group(2)}}}
    if tool == "desktop" and a.get("action") == "dark_mode" and (m := THEME.search(out)):
        return {"label": f"Windows {m.group(1)} -> {m.group(2)} mode",
                "reverse": {"tool": "desktop", "args": {"action": "dark_mode", "value": "off" if m.group(1) == "light" else "on"}}}
    if tool == "str_replace_editor" and a.get("command") in EDITS and a.get("path"):
        return {"label": f"{a['command']} {a['path']}",
                "reverse": {"tool": "str_replace_editor", "args": {"command": "undo_edit", "path": a["path"]}}}
    return None


def _same(call: Dict[str, Any], tool: str, args: Dict[str, Any]) -> bool:
    if call.get("tool") != tool:
        return False
    return all(str((args or {}).get(k)) == str(v) for k, v in (call.get("args") or {}).items())


def history(journal: Journal, window: int = WINDOW) -> List[Dict[str, Any]]:
    """Reversible calls in the journal window, oldest first, each with `done` set
    to the id of the call that reversed it (or None)."""
    started: Dict[tuple, tuple] = {}
    records: List[Dict[str, Any]] = []
    for e in journal.recent_events(window):
        p = e.get("payload") or {}
        key = (e.get("task_id"), p.get("id"))
        if e["type"] == "tool.started":
            started[key] = (p.get("name"), p.get("args") if isinstance(p.get("args"), dict) else {})
        elif e["type"] == "tool.completed":
            name, args = started.get(key, (p.get("name"), {}))
            for r in reversed(records):
                if r["done"] is None and _same(r["reverse"], name, args):
                    r["done"] = e["id"]
                    break
            rec = reverse_of(name, args, p.get("output"))
            if rec:
                records.append({**rec, "tool": name, "id": e["id"], "ts": e["ts"], "task_id": e.get("task_id"), "done": None})
    return records


def pending(journal: Journal, limit: int = 5) -> List[Dict[str, Any]]:
    """Reversible actions not yet undone, newest first."""
    return [r for r in reversed(history(journal)) if r["done"] is None][:limit]


class UndoTool(BaseTool):
    name: str = "undo"
    description: str = (
        "When the human says 'undo' or 'put it back': shows SYRAX's newest reversible actions (brightness, wallpaper, "
        "dark mode, file edits) and the exact call that reverses each. Then make that call yourself. This tool changes nothing."
    )
    parameters: dict = {"type": "object", "properties": {}, "required": []}
    journal_provider: Callable[[], Journal] = Field(default=get_journal, exclude=True)

    async def execute(self) -> ToolResult:
        rows = await asyncio.to_thread(pending, self.journal_provider())
        if not rows:
            return ToolResult(output="Nothing to undo: no reversible action of mine is pending.")
        lines = ["Newest first. To undo one, make exactly this call:"]
        for r in rows:
            rev = r.get("reverse") or {}
            lines.append(f"- {r.get('label')}: call `{rev.get('tool')}` with {json.dumps(rev.get('args'), ensure_ascii=False)}")
        return ToolResult(output="\n".join(lines))
