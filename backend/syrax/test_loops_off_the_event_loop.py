"""The proactive loops read the journal off the event loop. Live 2026-10-12
18:44 the reminder loop read it on the loop while a slow journal call in a
worker held the journal lock, and the whole server froze for over 60 s
(stall-20261012-184441.txt). Here the lock is held by another thread while
each loop body runs; the event loop must keep ticking."""

import asyncio
import threading
import time

from syrax import proactive, reminders, topics
from syrax.journal import Journal


def ticks_while_the_journal_is_locked(j, coro_fn, hold=0.8):
    locked, release = threading.Event(), threading.Event()

    def hog():
        with j._lock:
            locked.set()
            time.sleep(hold)

    async def main():
        t = threading.Thread(target=hog)
        t.start()
        locked.wait()
        job = asyncio.ensure_future(coro_fn())
        n = 0
        while not job.done():
            await asyncio.sleep(0.02)
            n += 1
        t.join()
        return n, job.result()
    return asyncio.run(main())


def test_reminders_fire_without_freezing_the_loop(tmp_path):
    j = Journal(tmp_path / "j.db")
    reminders.create(j, "stretch", time.time() - 5, now=time.time() - 60)
    n, fired = ticks_while_the_journal_is_locked(j, lambda: reminders.fire_due(j))
    assert n >= 10 and [f["text"] for f in fired] == ["stretch"]


def test_a_check_in_and_topic_news_do_not_freeze_the_loop(tmp_path):
    j = Journal(tmp_path / "j.db")
    n, _ = ticks_while_the_journal_is_locked(j, lambda: proactive.tick(j, now=time.time()))
    assert n >= 10
    topics.watch(j, "solar power")
    n, found = ticks_while_the_journal_is_locked(j, lambda: topics.check(j, fetch=lambda t: [{"title": "x", "url": "https://e/1"}]))
    assert n >= 10 and found and found[0]["topic"] == "solar power"
