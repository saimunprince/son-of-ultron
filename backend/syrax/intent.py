"""The intent ledger: what SYRAX is about to send or pay, written before it goes out.

Audit 2026-10-25 ("Task runtime"): external side effects (a message, a payment, a web or desktop
action) had no idempotency key, so a crash, a cancel or a timeout in the middle of one left nothing
that said "this may already have gone out", and a resumed or retried task could send it again.

An EXTERNAL_WRITE call (permissions.py: NET_SEND code, a skill declared EXTERNAL_WRITE, a desktop key
press or typed newline that submits text in a messaging app) is journaled as ``intent.recorded``
{tool, args_hash, summary, step} before it runs and ``intent.done`` {tool, args_hash, ok} after; the agent refuses the same call again while the first is still only recorded,
recovery classifies a crash inside it as EXTERNAL_UNCERTAIN, and a resume carries the summary.
Pure helpers only (stdlib): agent.py, core.py and journal.py all import this module.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

HASH_HEX = 16
SUMMARY_CHARS = 120
# the argument that says what goes out, in order of how telling it is: a message's text before its address
TELLING_KEYS = ("text", "message", "body", "content", "to", "recipient", "chat_id", "amount", "code", "url", "query", "action", "command")

HELD = ("Error: refused: the same {name} action may already have gone out (step {step}): check what happened "
        "first; do not repeat it blindly. This is final: do not retry it; do the rest or report.")
RESUME_NOTE = ("An external action may already have happened: {summary}. Never repeat it; verify with a read-only "
               "check and report.")


# A failed result that does not say the action did not happen: the call was abandoned or cut off while it ran
# (agent.py TOOL_TIMED_OUT, python_execute's "Execution timeout", a dropped connection). The request may have
# reached the other side before that, so the intent is uncertain, not done. A refused connection, a bad argument
# or a server's own error answer is a send that did not go out: done, and a retry is the model's choice.
UNCERTAIN = re.compile(r"(?i)did not answer within|execution timeout|\btimed?[ -]?out(?:error)?\b|read ?timeout|"
                       r"connection ?(?:was )?(?:reset|aborted)|remote ?(?:end closed|disconnected)|server ?disconnected|"
                       r"incomplete ?read")


def uncertain(output: Any) -> Optional[str]:
    """Why a failed EXTERNAL_WRITE call may still have gone out ("timed out", "connection lost"), else None."""
    m = UNCERTAIN.search(str(output or ""))
    if not m:
        return None
    return "connection lost" if re.search(r"(?i)connection|remote|disconnected|incomplete", m.group(0)) else "timed out"


def args_hash(args: Any) -> str:
    """sha256 of the canonical JSON of the call's arguments, first 16 hex digits: the idempotency key."""
    canonical = json.dumps(args if args is not None else {}, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:HASH_HEX]


def summary(tool: str, args: Any) -> str:
    """"<tool>: <the most telling argument>", at most SUMMARY_CHARS of it, for a notice or a resume note."""
    a = args if isinstance(args, dict) else {}
    if tool == "desktop" and a.get("action"):
        # a send through the desktop (permissions.MESSAGING_APPS): "desktop hotkey: enter", not "desktop: action=hotkey"
        what = " ".join(str(a.get("value") or a.get("target") or "").split())
        return f"desktop {a['action']}" + (f": {what[:SUMMARY_CHARS]}" if what else "")
    key = next((k for k in TELLING_KEYS if a.get(k) not in (None, "")), None)
    if key is None:
        key = next((k for k, v in a.items() if v not in (None, "")), None)
    if key is None:
        return tool
    value = " ".join(str(a[key]).split())
    if key not in ("text", "message", "body", "content", "code"):
        value = f"{key}={value}"
    return f"{tool}: {value[:SUMMARY_CHARS]}"


def key(tool: Any, hash_: Any) -> str:
    """The agent ledger's key: the tool and the hash, so two tools given identical arguments never hold each other."""
    return f"{tool}|{hash_}"


def entry(tool: str, args: Any, step: Optional[int] = None) -> Dict[str, Any]:
    """The ledger entry of one call: what intent.recorded carries."""
    return {"tool": tool, "args_hash": args_hash(args), "summary": summary(tool, args), "step": step}


def open_of(events: Iterable[Tuple[str, dict]]) -> List[Dict[str, Any]]:
    """The intents recorded and never done, from a task's (type, payload) events in order: a crash, a cancel
    or an exception between intent.recorded and intent.done leaves the entry open."""
    open_: Dict[str, Dict[str, Any]] = {}
    for type_, payload in events:
        h = str((payload or {}).get("args_hash") or "")
        if not h:
            continue
        if type_ == "intent.recorded":
            open_[h] = {"tool": payload.get("tool"), "args_hash": h, "summary": payload.get("summary"), "step": payload.get("step")}
        elif type_ == "intent.done":
            open_.pop(h, None)
    return list(open_.values())
