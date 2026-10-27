"""2026-10-27 integration run: test_queue_stall failed 3 times in 15 because its two requests were queued in the same
clock tick. Their `created` was equal, the journal lists tasks newest first with no order between equal times, and the
queue started the second request first. Requests that share a time keep the order they came in."""

import os

os.environ.setdefault("OPENMANUS_DISABLE_BROWSER_USE", "1")

from syrax import journal as jmod  # noqa: E402
from syrax.core import Core  # noqa: E402
from syrax.journal import Journal  # noqa: E402


def test_requests_queued_in_one_tick_keep_their_order(tmp_path, monkeypatch):
    monkeypatch.setattr(jmod, "_now", lambda: 1793090000.0)  # every row gets the same time
    c = Core(Journal(tmp_path / "j.db"))
    ids = [c.journal.start_task_sync(f"wish {i}", kind="conversation", pending=True) for i in range(6)]
    assert [q["task_id"] for q in c._pending()] == ids
    assert [q["position"] for q in c._pending()] == [1, 2, 3, 4, 5, 6]
