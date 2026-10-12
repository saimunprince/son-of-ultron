"""The event-loop stall watchdog: a blocked loop leaves the stacks of every
thread on disk and a stall.recovered event once it answers again; a healthy
loop leaves nothing. The release gate's pytest dumps stacks of a hung test."""

import asyncio
import time

from syrax import stallwatch, verify
from syrax.journal import Journal


def run_with_watchdog(tmp_path, block_s):
    j = Journal(tmp_path / "j.db")

    async def main():
        w = stallwatch.Watchdog(asyncio.get_running_loop(), j, check_s=0.05, stall_s=0.3, log_dir=tmp_path / "logs").start()
        await asyncio.sleep(0.2)
        time.sleep(block_s)  # a synchronous call that blocks the loop
        await asyncio.sleep(0.6)  # the loop answers again and the record is written
        w.stop()

    asyncio.run(main())
    return j


def test_a_blocked_loop_leaves_the_stacks_and_a_record(tmp_path):
    j = run_with_watchdog(tmp_path, 0.8)
    dumps = list((tmp_path / "logs").glob("stall-*.txt"))
    assert len(dumps) == 1
    text = dumps[0].read_text(encoding="utf-8")
    assert "event loop silent" in text and "most recent call first" in text
    (ev,) = j.events_of_type("stall.recovered")
    assert ev["payload"]["stuck_s"] >= 0.3 and ev["payload"]["stacks"] == str(dumps[0])


def test_a_healthy_loop_leaves_nothing(tmp_path):
    j = run_with_watchdog(tmp_path, 0.0)
    assert not (tmp_path / "logs").exists() and j.events_of_type("stall.recovered") == []


def test_the_gate_dumps_the_stacks_of_a_hung_test():
    gate = next(g for g in verify.default_gates() if g.name == "pytest")
    assert "faulthandler_timeout=300" in gate.cmd
