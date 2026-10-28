"""The emergency stop: an operator's persistent "SYRAX does nothing on its own" switch.

Audit 2026-10-28: the WS `stop` cancelled only the running task (the autonomy loop picked new work within one
interval), `cycle_now` ran a cycle with autonomy off, and SYRAX_AUTONOMY=1 overrode the operator's "off". The
emergency stop is a journal meta row that:

- survives restarts (the journal is the state),
- blocks the autonomy loop, a forced cycle and every self-started task (kinds autonomous and eval) at Core.submit,
- is set and cleared only by a human through the server's `estop` message (SYRAX's own code may not write the
  journal nor drive its own /ws: guard.py, auth.py), and only a human commit changes this file (devloop.JUDGES).

A human's own requests still run while it is on: the operator is present for those.
"""

import json
import time
from typing import Optional

META_KEY = "estop"
BLOCKED_KINDS = ("autonomous", "eval")


def state(journal) -> Optional[dict]:
    """The active stop {"at", "note", "by"}, or None when there is none (a broken row counts as ON: fail closed)."""
    raw = journal.get_meta(META_KEY)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return {"at": None, "note": "unreadable emergency-stop record (treated as on)", "by": None}
    return data if isinstance(data, dict) and data.get("on") else None


def active(journal) -> bool:
    try:
        return state(journal) is not None
    except Exception:
        return True  # a journal that cannot say is not a go-ahead


def set_stop(journal, note: str = "", by: str = "operator") -> dict:
    rec = {"on": True, "at": time.time(), "note": (note or "")[:300], "by": (by or "operator")[:120]}
    journal.set_meta(META_KEY, json.dumps(rec))
    journal.record_sync("estop.set", rec)
    return rec


def clear_stop(journal, note: str = "", by: str = "operator") -> None:
    journal.set_meta(META_KEY, json.dumps({"on": False, "at": time.time(), "by": (by or "operator")[:120]}))
    journal.record_sync("estop.cleared", {"note": (note or "")[:300], "by": (by or "operator")[:120]})


def refusal(kind: str) -> str:
    return f"emergency stop is on: SYRAX starts no {kind} work until the operator clears it"
