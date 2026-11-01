"""Owner's spec 2026-11-01 (F11): an objective must not become DONE because of an unrelated commit or another task's
GREEN gate (live: objective 42 closed on the daily ledger's own gate). A commit names the objective it was made for
(commit.created objective_id, and an "Objective: #<id>" trailer), and each check records the objective id, the
commit SHAs and the verification it rests on."""

import asyncio

from syrax.autonomy import judge
from syrax.journal import Journal


def obj(j, check, key=None):
    return j.add_objective_sync("x", None, 2, "selfmodel", check, key=key)


def own_task(j, o):
    t = j.start_task_sync("[AUTONOMOUS OBJECTIVE] x", kind="autonomous")
    j.record_sync("cycle.completed", {"objective_id": o["id"], "task_id": t, "outcome": "RAN"})
    return t


def test_an_unrelated_commit_does_not_close_change_released(tmp_path):
    j = Journal(tmp_path / "j.db")
    o = obj(j, {"kind": "change_released"})
    other = j.start_task_sync("someone else's work", kind="autonomous")
    j.record_sync("commit.created", {"commit": "aaa1", "files": ["x.py"], "summary": "other"}, task_id=other)
    assert judge(j, o, None)[0] == "RETRY"


def test_a_commit_naming_another_objective_never_counts(tmp_path):
    j = Journal(tmp_path / "j.db")
    o = obj(j, {"kind": "change_released"})
    t = own_task(j, o)
    j.record_sync("commit.created", {"commit": "bbb2", "files": ["x.py"], "summary": "s", "objective_id": o["id"] + 99}, task_id=t)
    assert judge(j, o, j.task(t))[0] == "RETRY"


def test_the_objectives_own_commit_closes_it_with_the_evidence(tmp_path):
    j = Journal(tmp_path / "j.db")
    o = obj(j, {"kind": "change_released"})
    t = own_task(j, o)
    j.record_sync("commit.created", {"commit": "ccc3", "files": ["x.py"], "summary": "s", "objective_id": o["id"],
                                     "verification_id": 7}, task_id=t)
    verdict, ev = judge(j, o, j.task(t))
    assert verdict == "DONE" and ev["objective_id"] == o["id"] and ev["commits"] == ["ccc3"] and ev["verification_ids"] == [7]


def test_another_tasks_green_gate_does_not_close_verification_green(tmp_path):
    j = Journal(tmp_path / "j.db")
    o = obj(j, {"kind": "verification_green"})
    ledger = j.start_task_sync("[MAINTENANCE] publish the rise ledger", kind="autonomous")
    j.record_verification_sync({"status": "GREEN", "gates": []}, task_id=ledger)
    verdict, ev = judge(j, o, None)
    assert verdict == "RETRY" and ev["ignored_other_tasks"]
    t = own_task(j, o)
    j.record_verification_sync({"status": "GREEN", "gates": []}, task_id=t)
    verdict, ev = judge(j, o, j.task(t))
    assert verdict == "DONE" and ev["objective_id"] == o["id"] and ev["verification_task"] == t and ev["verification_id"]


def test_a_tool_bug_needs_its_own_fix_before_a_good_call_counts(tmp_path):
    j = Journal(tmp_path / "j.db")
    o = obj(j, {"kind": "tool_verified", "tool": "desktop"}, key="tool-bug:desktop:backend/syrax/desktop.py:310")
    t = own_task(j, o)

    def call(ok=True):
        j.record_sync("tool.started", {"id": "c", "name": "desktop", "args": {}}, task_id=t)
        j.record_sync("tool.completed" if ok else "tool.failed", {"id": "c", "name": "desktop", "ok": ok, "output": "x"}, task_id=t)

    call()
    verdict, ev = judge(j, o, j.task(t))
    assert verdict == "RETRY" and "fixes the bug" in ev["missing"]  # a good call alone is no fix
    j.record_sync("commit.created", {"commit": "ddd4", "files": ["backend/syrax/desktop.py"], "summary": "fix", "objective_id": o["id"]}, task_id=t)
    call()
    verdict, ev = judge(j, o, j.task(t))
    assert verdict == "DONE" and ev["commits"] == ["ddd4"]


def test_a_release_names_its_objective_in_the_journal_and_in_git(tmp_path):
    from syrax.devloop import DevLoop
    from syrax.test_devloop import PASS, git, repo

    root = repo(tmp_path)
    j = Journal(tmp_path / "j.db")
    o = obj(j, {"kind": "change_released"})
    j.update_objective_sync(o["id"], status="ACTIVE", note="cycle")
    t = j.start_task_sync("[AUTONOMOUS OBJECTIVE] x", kind="autonomous")
    dl = DevLoop(j, root=root, gates=lambda: PASS, task_id_provider=lambda: t, snapshot_dir=tmp_path / "rb")
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 3\n")
    (root / "backend" / "syrax" / "test_three.py").write_text("from syrax.mod import VALUE\n\ndef test_v():\n    assert VALUE == 3\n")
    rep = asyncio.run(dl.release("VALUE 3", {"why": "objective", "risk": "none", "tests": "test_three"}))
    assert rep["outcome"] == "COMMITTED", rep
    ev = [e["payload"] for e in j.events(t) if e["type"] == "commit.created"][0]
    assert ev["objective_id"] == o["id"]
    assert f"Objective: #{o['id']}" in git(root, "log", "-1", "--format=%B")
