"""Known-good fallback, the journal's side.

When a core started from main does not come up (it exits, or /health stays
silent for CORE_BOOT_DEADLINE_S), the launcher (syrax.py) runs the last
known-good commit from a worktree of its own (.syrax/known-good) and runs

    python -m syrax.knowngood --from <failed commit> --to <known-good commit> --why <reason>

from that worktree's backend, with SYRAX_JOURNAL_FILE pointing at the live
journal, after the failed core has stopped and before the known-good core
starts: nobody owns the journal then, so this opens it without recovery and
writes through the journal's own API (never SQL by hand), then closes it.

It journals `restart.fallback` {from, to, why} and a reminder due
NOTICE_AFTER_S later: the known-good core's own reminder loop fires it once it
runs, which journals `reminder.fired` (the UI shows and speaks it) and raises a
desktop notification. That reaches the human even when no UI was connected at
boot, and a fallback core that also fails leaves the reminder pending for the
next start that comes up.

The code here runs from the known-good commit, never from the commit that
failed: whatever broke in main cannot break the notice.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import List, Optional

from syrax import reminders
from syrax.journal import DEFAULT_FILE, Journal

EVENT = "restart.fallback"
NOTICE_AFTER_S = 120  # the known-good core is up by then, and a UI that reconnects on its own has reconnected


def short(commit: str) -> str:
    return str(commit or "?")[:10]


def notice_text(from_commit: str, to_commit: str, why: str) -> str:
    """The reminder's sentence: what happened, what is safe, what the human does next."""
    head = (f"SYRAX could not start commit {short(from_commit)} ({' '.join(str(why or '').split())[:110]}) "
            f"and runs the last known-good commit {short(to_commit)}.")
    tail = " Main is untouched; self-improvement is off. Fix main, then run: python syrax.py --restart"
    return (head + tail)[:reminders.MAX_TEXT]


def record(journal: Journal, from_commit: str, to_commit: str, why: str, now: Optional[float] = None) -> dict:
    now = now if now is not None else time.time()
    payload = {"from": str(from_commit), "to": str(to_commit), "why": str(why or "")[:300]}
    journal.record_sync(EVENT, payload)
    r = reminders.create(journal, notice_text(from_commit, to_commit, why), now + NOTICE_AFTER_S, now=now)
    return {**payload, "reminder": r["id"], "due_ts": r["due_ts"]}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Journal a known-good fallback (run by syrax.py, not by hand).")
    ap.add_argument("--from", dest="from_commit", required=True, help="the commit that did not come up")
    ap.add_argument("--to", dest="to_commit", required=True, help="the known-good commit SYRAX runs instead")
    ap.add_argument("--why", default="", help="why the launcher fell back")
    a = ap.parse_args(argv)
    journal = Journal(os.getenv("SYRAX_JOURNAL_FILE", str(DEFAULT_FILE)), recover=False)
    try:
        if journal.read_only:  # a live core owns it: only the owner writes
            sys.stderr.write("the journal is owned by a running SYRAX; the fallback was not journaled\n")
            return 2
        sys.stdout.write(json.dumps(record(journal, a.from_commit, a.to_commit, a.why)) + "\n")  # the launcher logs it
        return 0
    finally:
        journal.close()


if __name__ == "__main__":
    sys.exit(main())
