"""Live 2026-10-15: in objective 232's attempt 3 the permission gate refused an
os.remove in python_execute; tool_stats counted the refusal as the tool's last
outcome, the self-model called python_execute FAILING and the cycle spent a
task on "python_execute failed on its last use, diagnose why". A refused call
is no use and no failure of the tool; it cannot make a verify objective DONE
either, and the matrix counts it the same way."""

import sqlite3
import time

from syrax import capmatrix as cm
from syrax.autonomy import derive_objectives, judge
from syrax.journal import Journal
from syrax.test_autonomy import make

REFUSED = "Error: refused: deletes files (DESTRUCTIVE) is not done in autonomous work"


def call(j, t, cid, ok=True, refused=False):
    j.record_sync("tool.started", {"id": cid, "name": "python_execute", "args": {"code": "x"}}, task_id=t)
    if ok:
        j.record_sync("tool.completed", {"id": cid, "name": "python_execute", "ok": True, "output": "ok"}, task_id=t)
    else:
        j.record_sync("tool.failed", {"id": cid, "name": "python_execute", "ok": False, "output": REFUSED if refused else "Error: boom",
                                      **({"refused": True} if refused else {})}, task_id=t)


def test_a_refused_call_does_not_make_the_tool_failing(tmp_path):
    j, core, a = make(tmp_path, tools=["python_execute", "terminate"])
    t = j.start_task_sync("[AUTONOMOUS OBJECTIVE] x", kind="autonomous")
    call(j, t, "a")
    call(j, t, "b", ok=False, refused=True)
    st = j.tool_stats()["python_execute"]
    assert (st["uses"], st["successes"], st["failures"], st["refused"], st["last_outcome"]) == (1, 1, 0, 1, "ok")
    cap = next(c for c in core.selfmodel.capabilities() if c["capability"] == "python_execute")
    assert cap["status"] == "VERIFIED"
    derive_objectives(j, core.selfmodel)
    assert not [o for o in j.objectives(limit=100) if (o["key"] or "").startswith("repair-capability:python_execute")]
    call(j, t, "c", ok=False)  # a real failure still counts
    st = j.tool_stats()["python_execute"]
    assert (st["uses"], st["failures"], st["last_outcome"]) == (2, 1, "fail")


def test_a_refused_call_cannot_verify_the_tool(tmp_path):
    j = Journal(tmp_path / "j.db")
    t0 = j.start_task_sync("earlier", kind="conversation")
    call(j, t0, "a")
    before = j.tool_stats()["python_execute"]["last_used"]
    time.sleep(0.05)
    o = j.add_objective_sync("Verify that the `python_execute` tool works", None, 5, "selfmodel",
                             {"kind": "tool_verified", "tool": "python_execute"}, key="verify-capability:python_execute")
    t = j.start_task_sync("verify python_execute", kind="autonomous")
    call(j, t, "b", ok=False, refused=True)
    assert j.tool_stats()["python_execute"]["last_used"] == before
    verdict, ev = judge(j, o, j.task(t))
    assert verdict == "RETRY" and ev["used_after_objective"] is False


def test_the_matrix_counts_refusals_like_the_journal(tmp_path):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("work", kind="autonomous")
    call(j, t, "a")
    call(j, t, "r", ok=False, refused=True)
    call(j, t, "r", ok=False, refused=True)
    call(j, t, "z", ok=False)
    theirs = j.tool_stats()
    j.close()
    c = sqlite3.connect(f"file:{(tmp_path / 'j.db').as_posix()}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    mine = cm.tool_stats(c, time.time())["python_execute"]
    keys = ("uses", "successes", "failures", "refused", "last_used", "last_outcome")
    assert {k: mine[k] for k in keys} == {k: theirs["python_execute"][k] for k in keys}
    assert (mine["uses"], mine["failures"], mine["refused"], mine["recent_fail"]) == (2, 1, 2, 1)
