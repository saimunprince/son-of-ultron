"""Journal.run fans out only the events its own call inserted. It fanned out every event after the id it began
at, so an event another coroutine recorded during a slow run() (derive_objectives, backup.snapshot), already
fanned out by its own record(), went out twice: a duplicate UI line, a reminder.fired spoken twice."""

import asyncio
import threading

import pytest

from syrax.journal import Journal


def test_an_event_recorded_during_a_slow_run_is_fanned_out_once(tmp_path):
    j = Journal(tmp_path / "j.db")
    seen = []

    async def sub(ev):
        seen.append((ev.id, ev.type))

    j.subscribe(sub)
    go = threading.Event()

    def slow():
        assert go.wait(10)
        j.set_meta("k", "v")  # a write that journals nothing
        j.record_sync("from.run", {"n": 1})
        return "ok"

    async def main():
        running = asyncio.ensure_future(j.run(slow))
        await asyncio.sleep(0.05)
        other = await j.record("reminder.fired", {"text": "tea"})  # another coroutine, meanwhile
        go.set()
        assert await running == "ok"
        return other

    other = asyncio.run(main())
    assert [t for _, t in seen].count("reminder.fired") == 1
    assert [t for _, t in seen].count("from.run") == 1
    assert seen[0] == (other.id, "reminder.fired")


def test_run_fans_out_what_it_committed_and_not_what_rolled_back(tmp_path):
    j = Journal(tmp_path / "j.db")
    seen = []

    async def sub(ev):
        seen.append(ev.type)

    j.subscribe(sub)

    def work():
        with pytest.raises(RuntimeError):
            with j._txn() as cur:
                j._insert_event(cur, 1.0, None, "rolled.back", {})
                raise RuntimeError("boom")
        # another writer now takes the rolled-back id; it is that writer's event, not this call's
        other = threading.Thread(target=j.record_sync, args=("other.writer", {}))
        other.start()
        other.join()
        j.record_sync("kept.one", {})
        j.record_sync("kept.two", {})

    asyncio.run(j.run(work))
    assert seen == ["kept.one", "kept.two"]
