"""SYRAX presentation engine: SYRAX decides what to show, the UI only draws it.

The engine observes the real event stream and produces presentation elements
from a small visual vocabulary. Elements are ephemeral: each carries an
attention level, a position, an optional ttl, what it replaces and which
events dismiss it. When nothing needs showing the plan is empty and the UI
returns to its minimal state. The model can also decide to present something
explicitly with the `present` tool.

Vocabulary (kinds): status, card, code, terminal, table, list, image,
notification. Positions: stage (the focused area above the feed) and overlay.
Attention: ambient, notice, focus.

Rules are state → presentation decisions living in the core, not in the
frontend; the frontend never infers what happened.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from pydantic import Field

from app.tool.base import BaseTool, ToolResult

from syrax.journal import Event, Journal

KINDS = ("status", "card", "code", "terminal", "table", "list", "image", "notification")
ATTENTION = ("ambient", "notice", "focus")
POSITIONS = ("stage", "overlay")
TASK_END = ("task.completed", "task.failed", "task.cancelled", "task.interrupted")
MAX_TEXT = 4000

Emit = Callable[[dict], Awaitable[None]]


def _clip(text: Any, n: int = MAX_TEXT) -> str:
    s = str(text or "")
    return s if len(s) <= n else s[:n] + "…"


MIN_FEEDBACK = 5          # decisions need evidence: at least this many human dismissals of a kind
QUICK_DISMISS_S = 5.0     # a median dismissal faster than this means "not wanted"
SHORT_TTL_S = 20.0


class PresentationEngine:
    def __init__(self, journal: Journal, emit: Optional[Emit] = None):
        self.journal = journal
        self.emit = emit  # broadcast to observers (set by the core)
        self.active: Dict[str, dict] = {}
        self._seq = itertools.count(1)
        self._by_slot: Dict[str, str] = {}  # slot → presentation_id (one element per slot)
        self._prefs_cache: Optional[Dict[str, dict]] = None
        self._prefs_ts = 0.0

    # ——— learning from the human: what gets dismissed fast is not wanted ———

    def preferences(self, refresh: bool = False) -> Dict[str, dict]:
        """Per kind, derived from journaled feedback: {"quiet": bool, "median_dismiss_after_s", "human_dismissed", "shown"}.
        A kind is "quiet" when at least MIN_FEEDBACK humans dismissals have a median under QUICK_DISMISS_S."""
        if not refresh and self._prefs_cache is not None and time.time() - self._prefs_ts < 60:
            return self._prefs_cache
        try:
            stats = self.journal.presentation_stats()
        except Exception:  # no journal, no evidence, no preference change
            return self._prefs_cache or {}
        prefs = {}
        for kind, st in stats.items():
            quiet = st["human_dismissed"] >= MIN_FEEDBACK and st["median_dismiss_after_s"] is not None and st["median_dismiss_after_s"] < QUICK_DISMISS_S
            prefs[kind] = {"quiet": quiet, **st}
        self._prefs_cache, self._prefs_ts = prefs, time.time()
        return prefs

    async def feedback(self, pid: str, action: str = "dismiss") -> bool:
        el = self.active.get(pid)
        if el is None:
            return False
        after_s = round(time.time() - el["created"], 2)
        await self._journal("presentation.feedback", {"presentation_id": pid, "kind": el["kind"], "action": action, "after_s": after_s, "source": el.get("source")}, el.get("task_id"))
        self._prefs_cache = None
        if action == "dismiss":
            await self.dismiss(pid, "dismissed by human")
        return True

    # ——— element lifecycle ———

    def _new_id(self) -> str:
        return f"p{next(self._seq)}-{int(time.time() * 1000) % 100000}"

    async def show(self, kind: str, purpose: str, data: Optional[dict] = None, *, attention: str = "notice",
                   position: str = "stage", priority: int = 3, ttl_s: Optional[float] = None,
                   slot: Optional[str] = None, dismiss_on: Optional[List[str]] = None,
                   task_id: Optional[str] = None, source: str = "engine") -> dict:
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r}; one of {', '.join(KINDS)}")
        if attention not in ATTENTION or position not in POSITIONS:
            raise ValueError("bad attention or position")
        if source == "engine":
            pref = self.preferences().get(kind)
            if pref and pref["quiet"]:  # evidence says humans do not want this kind lingering
                ttl_s = min(ttl_s or SHORT_TTL_S, SHORT_TTL_S)
                attention = "ambient" if attention != "focus" else attention
        replaces = self._by_slot.get(slot) if slot else None
        pid = self._new_id()
        element = {
            "presentation_id": pid,
            "kind": kind,
            "purpose": purpose,
            "data": data or {},
            "attention": attention,
            "position": position,
            "priority": max(1, min(int(priority), 5)),
            "ttl_s": ttl_s,
            "replaces": replaces,
            "dismiss_on": list(dismiss_on or []),
            "slot": slot,
            "source": source,
            "created": time.time(),
            "task_id": task_id,
        }
        if replaces:
            self.active.pop(replaces, None)
        self.active[pid] = element
        if slot:
            self._by_slot[slot] = pid
        await self._journal("presentation.created", element, task_id)
        return element

    async def dismiss(self, pid: str, reason: str) -> bool:
        el = self.active.pop(pid, None)
        if el is None:
            return False
        if el.get("slot") and self._by_slot.get(el["slot"]) == pid:
            self._by_slot.pop(el["slot"], None)
        await self._journal("presentation.dismissed", {"presentation_id": pid, "reason": reason, "kind": el["kind"]}, el.get("task_id"))
        return True

    async def dismiss_where(self, pred: Callable[[dict], bool], reason: str) -> int:
        n = 0
        for pid in [p for p, el in list(self.active.items()) if pred(el)]:
            n += await self.dismiss(pid, reason)
        return n

    async def expire(self, now: Optional[float] = None) -> int:
        now = now or time.time()
        return await self.dismiss_where(lambda el: el["ttl_s"] is not None and el["created"] + el["ttl_s"] <= now, "expired")

    def plan(self) -> dict:
        elements = sorted(self.active.values(), key=lambda e: (-e["priority"], e["created"]))
        return {"elements": elements, "minimal": not elements}

    async def _journal(self, kind: str, payload: dict, task_id: Optional[str]) -> None:
        # Journaled task-less (the payload carries task_id) so a task's own event
        # list stays a record of what it did, not of what was drawn; the
        # journal's fan-out delivers the wire event to observers.
        try:
            await self.journal.record(kind, {**payload, "task_id": task_id})
        except Exception:
            if self.emit is not None:  # never lose the picture because of bookkeeping
                head, _, tail = kind.partition(".")
                await self.emit({"type": head, "event": tail, **payload, "unjournaled": True})

    # ——— rules: real events → decisions ———

    async def on_event(self, ev: Event) -> None:
        t, p, tid = ev.type, ev.payload, ev.task_id
        await self.expire()
        if t == "task.started":
            await self.show("status", "what SYRAX is working on", {"text": p.get("goal", ""), "kind": p.get("kind")},
                            attention="ambient", priority=2, slot="task", dismiss_on=list(TASK_END), task_id=tid)
        elif t == "tool.started":
            name = str(p.get("name") or "")
            args = p.get("args") if isinstance(p.get("args"), dict) else {}
            if name in ("python_execute",):
                await self.show("code", f"code being executed by {name}", {"language": "python", "code": _clip(args.get("code")), "tool": name},
                                priority=3, slot="tool", ttl_s=120, task_id=tid)
            elif name == "str_replace_editor" and args.get("command") in ("create", "str_replace", "insert"):
                await self.show("code", "file being edited", {"language": "diff", "path": args.get("path"), "command": args.get("command"),
                                                          "code": _clip(args.get("new_str") or args.get("file_text") or "")},
                                priority=3, slot="tool", ttl_s=120, task_id=tid)
            elif name.startswith("browser_") or name == "desktop":
                await self.show("status", f"operating {name}", {"text": _clip(json.dumps(args, ensure_ascii=False), 300), "tool": name},
                                attention="ambient", priority=2, slot="tool", ttl_s=60, task_id=tid)
            elif name == "research":
                await self.show("status", "researching", {"text": args.get("question", ""), "tool": name},
                                attention="ambient", priority=2, slot="tool", ttl_s=120, task_id=tid)
        elif t == "tool.completed":
            name = str(p.get("name") or "")
            if name == "python_execute":
                await self.show("terminal", "output of the executed code", {"text": _clip(p.get("output"))},
                                priority=3, slot="tool", ttl_s=90, task_id=tid)
        elif t == "tool.failed":
            await self.show("notification", "a tool failed", {"text": _clip(p.get("output"), 600), "tool": p.get("name"), "level": "error"},
                            attention="focus", priority=4, slot="alert", ttl_s=45, task_id=tid)
        elif t == "research.completed":
            await self.show("list", "sources found", {"title": _clip(p.get("question"), 120), "items": [], "stored": p.get("stored"), "sources": p.get("sources")},
                            priority=3, slot="tool", ttl_s=180, task_id=tid)
        elif t == "final":
            await self.show("card", "the reply", {"text": _clip(p.get("text"), 1500)}, priority=3, slot="reply", ttl_s=90, task_id=tid)
        elif t == "ask":
            await self.show("notification", "SYRAX needs an answer", {"text": _clip(p.get("question"), 600), "level": "question"},
                            attention="focus", priority=5, slot="alert", dismiss_on=["answer", *TASK_END], task_id=tid)
        elif t == "task.interrupted":
            await self.show("notification", "an interrupted task was recovered", {"text": f"{p.get('goal', '')} · step {p.get('step')} · {p.get('recovery_state')}", "level": "warn"},
                            attention="focus", priority=4, slot="alert", ttl_s=120, task_id=tid)
        elif t == "commit.created":
            await self.show("card", "a change was committed", {"text": f"{str(p.get('commit', ''))[:10]} {p.get('summary', '')}", "files": p.get("files")},
                            priority=3, slot="reply", ttl_s=120, task_id=tid)
        elif t == "rollback.created":
            await self.show("notification", "a change was rolled back", {"text": str(p.get("reason", "")), "level": "warn"},
                            attention="focus", priority=4, slot="alert", ttl_s=90, task_id=tid)
        elif t == "skill.verified":
            await self.show("card", "a new skill exists", {"text": f"{p.get('skill')} v{p.get('version')} · {p.get('tests_passed')} tests passed"},
                            priority=3, slot="reply", ttl_s=90, task_id=tid)
        # dismissals declared by the elements themselves
        await self.dismiss_where(lambda el: t in el["dismiss_on"], f"dismissed by {t}")
        if t in TASK_END:
            # the task is over: tool views go, the reply/alerts may linger until their ttl
            await self.dismiss_where(lambda el: el.get("slot") == "tool", "task ended")

    async def on_direct(self, event: dict) -> None:
        """Direct (non-journaled) events: errors deserve attention too."""
        if event.get("type") == "error":
            await self.show("notification", "an error", {"text": _clip(event.get("message"), 600), "level": "error"},
                            attention="focus", priority=4, slot="alert", ttl_s=45)


class PresentTool(BaseTool):
    name: str = "present"
    description: str = (
        "Decide to show the human something on the stage: a card of text, a code block, a table "
        "(rows of cells), a list, or a notification. Use it when a visual beats prose (a table of "
        "results, a code snippet, a comparison). The element disappears after ttl_s seconds or when "
        "you replace it; use kind='none' to clear the stage."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["card", "code", "table", "list", "notification", "none"]},
            "title": {"type": "string"},
            "text": {"type": "string", "description": "for card/code/notification"},
            "language": {"type": "string", "description": "for code"},
            "rows": {"type": "array", "items": {"type": "array", "items": {"type": ["string", "number", "boolean", "null"]}}, "description": "for table; first row = header"},
            "items": {"type": "array", "items": {"type": "string"}, "description": "for list"},
            "ttl_s": {"type": "number", "description": "seconds to stay (default 120)"},
            "attention": {"type": "string", "enum": ["ambient", "notice", "focus"]},
        },
        "required": ["kind"],
    }
    engine: Optional[Any] = Field(default=None, exclude=True)
    task_id_provider: Optional[Callable[[], Optional[str]]] = Field(default=None, exclude=True)

    async def execute(self, kind: str, title: str = "", text: str = "", language: str = "", rows: Optional[list] = None,
                      items: Optional[list] = None, ttl_s: float = 120, attention: str = "notice") -> ToolResult:
        if self.engine is None:
            return ToolResult(error="presentation engine unavailable")
        tid = self.task_id_provider() if self.task_id_provider else None
        if kind == "none":
            n = await self.engine.dismiss_where(lambda el: el.get("source") == "model", "cleared by SYRAX")
            return ToolResult(output=f"stage cleared ({n} element(s))")
        data: Dict[str, Any] = {"title": _clip(title, 200)}
        if kind in ("card", "notification"):
            if not text:
                return ToolResult(error="text required")
            data["text"] = _clip(text)
        elif kind == "code":
            if not text:
                return ToolResult(error="text required")
            data.update({"code": _clip(text), "language": language or "text"})
        elif kind == "table":
            if not rows or not all(isinstance(r, list) for r in rows):
                return ToolResult(error="rows (list of lists) required")
            data["rows"] = [[_clip(c, 200) for c in r[:12]] for r in rows[:50]]
        elif kind == "list":
            if not items:
                return ToolResult(error="items required")
            data["items"] = [_clip(i, 300) for i in items[:50]]
        else:
            return ToolResult(error=f"unknown kind {kind!r}")
        try:
            el = await self.engine.show(kind, title or f"{kind} chosen by SYRAX", data, attention=attention, priority=4,
                                        ttl_s=max(5.0, min(float(ttl_s or 120), 3600.0)), slot="model", task_id=tid, source="model")
        except ValueError as e:
            return ToolResult(error=str(e))
        return ToolResult(output=f"shown {kind} {el['presentation_id']} for {el['ttl_s']}s")
