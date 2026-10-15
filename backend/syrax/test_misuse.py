"""From 2026-09-30 to 2026-10-15 the cycle spent 40 tasks on "the tool failed
on its last use, diagnose why"; 38 were DONE on the first harmless call, some
with an invented cause, because the failure was the caller's: bad SQL to
journal_query, an old_str not in the file, a diff that does not apply, an
exception in its own python. Such a failure still counts as a failed call,
but it does not make the tool FAILING or draw a repair objective."""

import sqlite3
import time

from syrax import capmatrix as cm
from syrax.autonomy import derive_objectives
from syrax.journal import Journal, misuse
from syrax.test_autonomy import make

OBS = "Observed output of cmd `{}` executed:\n"
CALLER = {
    "journal_query": "Error: no such column: error. Schema: archive(id, ts, head)",
    "str_replace_editor": "Error: No replacement was performed: old_str did not appear verbatim in C:\\x.py.",
    "apply_patch": "Error: apply_patch refused: the patch does not apply cleanly: error: patch failed: backend/syrax/m.py:3",
    "python_execute": "{'observation': \"name 'os' is not defined\", 'success': False}",
}
TOOL = {
    "python_execute": "{'observation': 'Execution timeout after 30 seconds', 'success': False}",
    "desktop": "Error",
    "journal_query": "Error: database is locked",
}


def test_caller_mistakes_are_told_from_tool_failures():
    for name, out in CALLER.items():
        assert misuse(name, OBS.format(name) + out), name
    for name, out in TOOL.items():
        assert not misuse(name, OBS.format(name) + out), name
    assert not misuse("python_execute", "{'observation': '', 'success': False}")
    assert not misuse("python_execute", "{'observation': 'Error: the python_execute worker exited with code 1', 'success': False}")
    assert not misuse(None, "Error: no such column: x. Schema: y")


def call(j, t, name, cid, out=None):
    j.record_sync("tool.started", {"id": cid, "name": name, "args": {}}, task_id=t)
    if out is None:
        j.record_sync("tool.completed", {"id": cid, "name": name, "ok": True, "output": "ok"}, task_id=t)
    else:
        j.record_sync("tool.failed", {"id": cid, "name": name, "ok": False, "output": OBS.format(name) + out}, task_id=t)


def test_a_caller_mistake_draws_no_repair_objective(tmp_path):
    j, core, a = make(tmp_path, tools=["journal_query", "python_execute", "terminate"])
    t = j.start_task_sync("[AUTONOMOUS OBJECTIVE] x", kind="autonomous")
    call(j, t, "journal_query", "a")
    call(j, t, "journal_query", "b", CALLER["journal_query"])
    call(j, t, "python_execute", "c", TOOL["python_execute"])
    st = j.tool_stats()["journal_query"]
    assert (st["failures"], st["misuse"], st["last_outcome"]) == (1, 1, "misuse")
    caps = {c["capability"]: c for c in core.selfmodel.capabilities()}
    assert caps["journal_query"]["status"] == "VERIFIED" and caps["python_execute"]["status"] == "FAILING"
    derive_objectives(j, core.selfmodel)
    keys = [o["key"] or "" for o in j.objectives(limit=100)]
    assert not [k for k in keys if k.startswith("repair-capability:journal_query")]
    assert [k for k in keys if k.startswith("repair-capability:python_execute")]  # a timeout may be the tool's own


def test_only_mistakes_and_no_success_is_not_tested_and_the_matrix_agrees(tmp_path):
    j, core, a = make(tmp_path, tools=["str_replace_editor", "terminate"])
    t = j.start_task_sync("work", kind="autonomous")
    call(j, t, "str_replace_editor", "a", CALLER["str_replace_editor"])
    caps = {c["capability"]: c for c in core.selfmodel.capabilities()}
    assert caps["str_replace_editor"]["status"] == "NOT_TESTED"
    call(j, t, "str_replace_editor", "b")
    call(j, t, "str_replace_editor", "c", CALLER["str_replace_editor"])
    theirs = j.tool_stats()["str_replace_editor"]
    db = tmp_path / "check.db"
    j2 = Journal(db)
    t2 = j2.start_task_sync("work", kind="autonomous")
    call(j2, t2, "apply_patch", "a")
    call(j2, t2, "apply_patch", "b", CALLER["apply_patch"])
    call(j2, t2, "desktop", "c", TOOL["desktop"])
    mine_j = j2.tool_stats()
    j2.close()
    c = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    mine = cm.tool_stats(c, time.time())
    for name in ("apply_patch", "desktop"):
        assert {k: mine[name][k] for k in ("uses", "failures", "last_outcome")} == {k: mine_j[name][k] for k in ("uses", "failures", "last_outcome")}
    assert mine["apply_patch"]["last_outcome"] == "misuse" and mine["desktop"]["last_outcome"] == "fail"
    assert (theirs["successes"], theirs["failures"], theirs["misuse"], theirs["last_outcome"]) == (1, 2, 2, "misuse")
