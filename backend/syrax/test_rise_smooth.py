"""EVOLUTION_PLAN direction 298 (human-impact evaluation): smooth_requests counts the human's requests that ended
SUCCESS and cost them nothing more: no question, no permission prompt or refusal, not disputed and not undone by the
next request. A seeded journal gives known answers."""

import time

from syrax import journal as jmod
from syrax import rise
from syrax.journal import Journal


def test_smooth_requests_from_a_seeded_journal(tmp_path, monkeypatch):
    now = time.time()
    j = Journal(tmp_path / "j.db")
    clock = [now - 3600]

    def tick(s=60):
        clock[0] += s
        monkeypatch.setattr(jmod, "_now", lambda: clock[0])

    def request(goal, status="SUCCESS", events=(), tool=None):
        tick()
        t = j.start_task_sync(goal, kind="conversation")
        for e in events:
            j.record_sync(e, {"question": "?"} if e == "ask" else {"tool": "desktop"}, task_id=t)
            if e == "ask":
                j.record_sync("answer", {"text": "yes"}, task_id=t)
        if tool:
            j.record_sync("tool.started", {"id": "u1", "name": tool, "args": {}}, task_id=t)
        tick(5)
        if status == "FAILED":
            j.record_sync("task.failed", {"error": "no"}, task_id=t)
        else:
            j.record_sync("final", {"text": "ok"}, task_id=t)
            j.record_sync("task.completed", {"status": status, "result": "ok"}, task_id=t)
        return t

    request("what is the weather")                      # smooth
    request("delete old logs", events=("ask",))         # asked
    request("set volume to 80")                         # undone by the next one
    request("undo that", tool="undo")                   # smooth itself
    request("play lofi music")                          # disputed by the next one
    request("it's not playing")                         # smooth itself (nothing after it)
    request("open the report", status="FAILED")         # not SUCCESS
    request("send the mail", events=("permission.refused",))
    j.close()
    m = rise.measure(tmp_path / "j.db", now=now + 10)
    row = next(r for r in m["metrics"] if r["id"] == "smooth_requests")
    assert row["last"]["value"] == 37.5, row  # 3 of 8
    for part in ("1 asked", "1 undone", "1 disputed", "1 not SUCCESS", "1 permission"):
        assert part in row["last"]["detail"], row["last"]["detail"]
