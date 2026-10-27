"""The task phase model (F4): what SYRAX is doing, read from what it does.

Every task moves through understand, plan, act, observe and verify. The phase
comes from the events themselves, never from what the model says it is doing:

  understand  the task started and nothing is decided yet
  plan        the model's first decision to use a tool
  act         a tool that changes something runs (claims.changes_something)
  observe     a tool that only reads runs, or the model reads what came back
  verify      a checking tool runs (release, skill_test, experiment,
              compare_versions), or the final answer is being checked

The phase is a pure function of events the journal already records (think,
tool.started, final), so it is not stored again: `path(events)` recomputes a
task's phases from its journal, and the core sends each change live to the UI
as a `phase` message {phase, from, step, tool, target}. This is the first
layer of Visible Work Presence.

This file presents SYRAX's own work to the human, so SYRAX's own releases may
not change it (devloop.JUDGES).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

PHASES = ("understand", "plan", "act", "observe", "verify")
VERIFY_TOOLS = frozenset({"release", "skill_test", "experiment", "compare_versions"})
QUIET_TOOLS = frozenset({"terminate", "ask_human"})  # they end or pause a phase, they are not one


def target_of(name: str, args: Dict[str, Any]) -> Optional[str]:
    """What the tool acts on (a path, an app, a URL), as the permission check sees it."""
    try:
        from syrax import permissions

        targets = permissions.classify(name, args).targets
    except Exception:
        targets = []
    if targets:
        return str(targets[0])[:200]
    for key in ("path", "target", "url", "query", "place", "name"):
        if isinstance(args.get(key), str) and args[key].strip():
            return args[key].strip()[:200]
    return None


def phase_of_tool(name: str, args: Dict[str, Any]) -> str:
    """verify for checking tools; act when the call changes something; observe when it only reads."""
    from syrax import permissions
    from syrax.claims import changes_something

    if name in VERIFY_TOOLS:
        return "verify"
    if name in permissions.DECLARED:  # a skill: its declared level says whether it changes anything
        return "observe" if permissions.DECLARED[name] in (permissions.READ_ONLY, permissions.EXTERNAL_READ) else "act"
    if name == "desktop" and str(args.get("action") or "") in permissions.DESKTOP_READ:
        return "observe"
    return "act" if changes_something(name, args) else "observe"


def _to(current: Optional[str], phase: str, step: Any = None, tool: Optional[str] = None,
        target: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if phase == current:
        return None
    out: Dict[str, Any] = {"phase": phase, "from": current}
    if isinstance(step, int):
        out["step"] = step
    if tool:
        out["tool"] = tool
    if target:
        out["target"] = target
    return out


def path(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A task's phase transitions, recomputed from its journaled events (oldest
    first), each with the id of the event that caused it."""
    out: List[Dict[str, Any]] = []
    current: Optional[str] = None
    tools_run = 0
    for e in events:
        kind, payload = e.get("type"), e.get("payload") or {}
        if kind == "task.started":
            nxt: Optional[Dict[str, Any]] = _to(current, "understand")
        else:
            nxt = after(current, str(kind), payload, tools_run)
        if kind == "tool.started":
            tools_run += 1
        if nxt is not None:
            current = nxt["phase"]
            out.append({**nxt, "event_id": e.get("id")})
    return out


def after(current: Optional[str], kind: str, event: Dict[str, Any], tools_run: int) -> Optional[Dict[str, Any]]:
    """The phase.changed payload this journaled agent event causes, or None."""
    step = event.get("step")
    if kind == "think":
        if tools_run == 0:
            return _to(current, "plan", step) if event.get("tools") else None
        return None if current == "verify" else _to(current, "observe", step)
    if kind == "tool.started":
        name = str(event.get("name") or "")
        if name in QUIET_TOOLS:
            return None
        args = event.get("args") if isinstance(event.get("args"), dict) else {}
        return _to(current, phase_of_tool(name, args), step, name, target_of(name, args))
    if kind == "final":
        return _to(current, "verify", step)
    return None
