"""Event-loop stall watchdog: when SYRAX's event loop stops answering, find out why.

Live 2026-10-12: twice (13:38-13:53 and 14:21-15:04) the running SYRAX's
event loop blocked: no cycle ran, its 10-minute sleep could not wake, and it
came back the moment a release gate's pytest on the same machine ended.
Nothing in the log said what it was waiting on.

A daemon thread asks the loop to run a no-op every CHECK_S. When the loop has
not answered for STALL_S, the stacks of every thread are written to
backend/logs/stall-<time>.txt (once per stall). When the loop answers again,
a `stall.recovered` event records how long it was stuck and which file holds
the stacks.
"""

from __future__ import annotations

import asyncio
import faulthandler
import threading
import time
from pathlib import Path
from typing import Optional

from syrax.journal import BACKEND_ROOT

CHECK_S = 5.0
STALL_S = 60.0
LOG_DIR = BACKEND_ROOT / "logs"


class Watchdog:
    def __init__(self, loop: asyncio.AbstractEventLoop, journal, check_s: float = CHECK_S, stall_s: float = STALL_S,
                 log_dir: Path = LOG_DIR) -> None:
        self.loop, self.journal = loop, journal
        self.check_s, self.stall_s, self.log_dir = check_s, stall_s, Path(log_dir)
        self.last_answer = time.monotonic()
        self.stalled_since: Optional[float] = None
        self.dump: Optional[str] = None
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name="syrax-stall-watchdog", daemon=True)

    def start(self) -> "Watchdog":
        self.thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _answered(self) -> None:
        now = time.monotonic()
        if self.stalled_since is not None:
            stuck = round(now - self.stalled_since, 1)
            payload = {"stuck_s": stuck, "stacks": self.dump}
            self.stalled_since, self.dump = None, None
            asyncio.ensure_future(self._record(payload))
        self.last_answer = now

    async def _record(self, payload: dict) -> None:
        try:
            await self.journal.record("stall.recovered", payload)
        except Exception:
            pass

    def _write_stacks(self) -> str:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        path = self.log_dir / f"stall-{time.strftime('%Y%m%d-%H%M%S')}.txt"
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"SYRAX event loop silent for {self.stall_s:.0f}s+; every thread's stack:\n\n")
            f.flush()
            faulthandler.dump_traceback(file=f, all_threads=True)
        return str(path)

    def _run(self) -> None:
        while not self._stop.wait(self.check_s):
            try:
                self.loop.call_soon_threadsafe(self._answered)
            except RuntimeError:  # the loop is closed: SYRAX is shutting down
                return
            silent = time.monotonic() - self.last_answer
            if silent >= self.stall_s and self.stalled_since is None:
                self.stalled_since = self.last_answer
                try:
                    self.dump = self._write_stacks()
                except Exception as e:
                    self.dump = f"could not write the stacks: {e}"
