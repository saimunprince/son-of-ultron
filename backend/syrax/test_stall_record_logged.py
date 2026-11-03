"""Audit 2026-11-01 (LIFE-10): a stall.recovered that the journal refused was swallowed without a log line."""

import asyncio

from app.logger import logger
from syrax.stallwatch import Watchdog


class _Broken:
    async def record(self, *a, **k):
        raise RuntimeError("database is locked")


def test_a_lost_stall_record_is_logged(tmp_path):
    lines = []
    sink = logger.add(lines.append, level="WARNING")
    try:
        w = Watchdog.__new__(Watchdog)
        w.journal = _Broken()
        asyncio.run(w._record({"stuck_s": 12.5, "stacks": None}))
    finally:
        logger.remove(sink)
    assert any("stall.recovered" in str(m) and "database is locked" in str(m) for m in lines)
