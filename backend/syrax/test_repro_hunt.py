"""Brief Factory phase 2 (2026-10-22): SYRAX hunts the repro of its own failures. Measured on the journal: none of the
259 objectives SYRAX derived for itself ever changed its code. A hunt is derived only from a failure with a code
cause in a non-judge module (a tool's own error in two tasks, a quality case that failed twice the same way after
SYRAX's own nudge or check, an exception in two tasks), never from a caller's mistake, the environment or a single
run. Its task leaves a test and a fix in its worktree; judge code requires the test to quote the evidence, proves
both on a clean tree and files the brief."""

import asyncio
import time

from syrax import autonomy as auto
from syrax import contracts, repro
from syrax.autonomy import judge
from syrax.journal import Journal
from syrax.test_repro_prove import FIX, REPRO, TEST, shaped_repo

ERROR = "Observed output of cmd `present` executed:\nError: unknown argument(s) ['header']; use kind, title, text, rows, items"


def failed_call(j, t, name, output, args):
    j.record_sync("tool.started", {"id": f"c-{t}", "name": name, "args": args}, task_id=t)
    j.record_sync("tool.failed", {"id": f"c-{t}", "name": name, "ok": False, "output": output}, task_id=t)


def journal_after_watermark(tmp_path):
    j = Journal(tmp_path / "j.db")
    j.set_meta(repro.WATERMARK, str(time.time() - 60))
    return j


def test_only_a_tools_own_error_in_two_tasks_is_a_signal(tmp_path):
    root = shaped_repo(tmp_path)
    j = journal_after_watermark(tmp_path)
    for i in range(2):
        t = j.start_task_sync("show a table", kind="eval")
        failed_call(j, t, "present", ERROR, {"kind": "table", "header": ["name", "value"], "rows": [["a", 1]]})
    t = j.start_task_sync("edit", kind="eval")  # the caller's mistake
    failed_call(j, t, "str_replace_editor", "Error: No replacement was performed: old_str did not appear verbatim in x.py.", {})
    t = j.start_task_sync("browse", kind="eval")  # the environment
    failed_call(j, t, "desktop", "Error: connection refused by the host", {})
    for i in range(2):  # a judge file's tool is fixed by a human
        t = j.start_task_sync("run code", kind="eval")
        failed_call(j, t, "python_execute", "Observed output of cmd `python_execute` executed:\n{'observation': 'Execution timeout after 60 seconds'}", {})
    found = repro.signals(j, root=root)
    assert [s["kind"] for s in found] == ["tool"] and found[0]["tool"] == "present"
    assert found[0]["module"] == "backend/syrax/presentation.py" and found[0]["args"]["header"] == ["name", "value"]
    assert repro.signals(Journal(tmp_path / "other.db"), root=root) == []  # nothing failed, nothing to hunt


def test_a_case_is_hunted_only_after_two_same_failures_with_a_syrax_step(tmp_path):
    root = shaped_repo(tmp_path)
    j = journal_after_watermark(tmp_path)
    rows = []
    for nudge in (True, True):
        t = j.start_task_sync("Using apply_patch, create ...", kind="eval")
        if nudge:
            j.record_sync("claim.rejected", {"text": "The request asks you to use `release`", "task_kind": "eval"}, task_id=t)
        rows.append([{"id": "self_patch_new", "ok": False, "task_id": t,
                      "checks": [{"check": "tool release not used", "ok": False, "detail": "tools: ['apply_patch', 'release']"}]}])
    j.add_quality_run_sync(rows[0], 0.0, "BASELINE")
    j.add_quality_run_sync(rows[1], 0.0, "PASS")
    found = repro.signals(j, root=root)
    assert [s["case"] for s in found] == ["self_patch_new"] and "Do not call release" in found[0]["prompt"]
    j2 = journal_after_watermark(tmp_path / "b")
    for _ in range(2):  # the same failure, but nothing of SYRAX's own in the trace: the model's choice
        t = j2.start_task_sync("Using apply_patch, create ...", kind="eval")
        j2.add_quality_run_sync([{"id": "self_patch_new", "ok": False, "task_id": t,
                                  "checks": [{"check": "tool release not used", "ok": False}]}], 0.0, "PASS")
    assert repro.signals(j2, root=root) == []


def test_the_same_exception_in_two_tasks_is_a_signal_and_maintenance_is_not(tmp_path):
    root = shaped_repo(tmp_path)
    j = journal_after_watermark(tmp_path)
    for goal in ("remember my editor", "remember my shell", "[MAINTENANCE] publish the rise ledger"):
        t = j.start_task_sync(goal, kind="conversation")
        j.record_sync("task.failed", {"error": "TypeError: unsupported operand type(s) for +: 'NoneType' and 'str'"}, task_id=t)
    found = repro.signals(j, root=root)
    assert [s["kind"] for s in found] == ["task"] and len(found[0]["tasks"]) == 2


def test_hunts_are_derived_one_at_a_time_after_the_watermark(tmp_path):
    root = shaped_repo(tmp_path)
    j = Journal(tmp_path / "j.db")
    assert repro.derive(j, root=root) == 0 and j.get_meta(repro.WATERMARK)  # the first call only sets the watermark
    for i in range(2):
        t = j.start_task_sync("show a table", kind="eval")
        failed_call(j, t, "present", ERROR, {"kind": "table", "header": ["name", "value"]})
    assert repro.derive(j, root=root) == 1
    hunt = [o for o in j.objectives(limit=10) if o["source"] == "repro"][0]
    assert hunt["check_spec"]["kind"] == repro.HUNT_KIND and hunt["priority"] == 2 and hunt["key"].endswith(":g1")
    assert hunt["goal"].startswith(repro.HUNT_MARK) and '"header"' in hunt["goal"]
    assert repro.derive(j, root=root) == 0  # one live hunt at a time


def test_a_test_must_quote_the_evidence():
    assert repro.bound(REPRO, ["expected add(2, 3) == 5; add(2, 3) returned -1"])
    assert not repro.bound("from syrax.selfedit import TEST_TIMEOUT_S\n\n\ndef test_x():\n    assert TEST_TIMEOUT_S == 400\n",
                           ["unknown argument(s) ['header']"])


def hunt_with_task(tmp_path, final, snapshot_text):
    root = shaped_repo(tmp_path)
    j = Journal(tmp_path / "j.db")
    o = j.add_objective_sync(f"{repro.HUNT_MARK} add() subtracts", "test", 2, "repro", {"kind": repro.HUNT_KIND, "signal": "tool:calc:1"},
                             key="repro:tool:calc:1:g1",
                             evidence={"signal": {"id": "tool:calc:1", "summary": "add(2, 3) returned -1"}, "sources": ["expected add(2, 3) == 5; add(2, 3) returned -1"]})
    t = j.start_task_sync(o["goal"], kind="autonomous")
    snap = tmp_path / "snap.patch"
    snap.write_bytes(snapshot_text.encode())
    j.record_sync("final", {"text": final}, task_id=t)
    j.record_sync("rollback.created", {"snapshot": str(snap), "files": {}}, task_id=t)
    j.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t)
    return root, j, o, j.task(t)


def test_a_proven_hunt_files_the_brief_that_lands_it(tmp_path, monkeypatch):
    monkeypatch.setattr(auto, "REPO_ROOT_PATH", tmp_path / "live")
    root, j, o, task = hunt_with_task(tmp_path, "calc.add subtracts instead of adding.", FIX + f"\n# untracked: {TEST}\n" + REPRO)
    out = repro.harvest(j, o, task, root)
    assert out["event"] == "repro.proven" and out["verdict"] == "PROVEN", out
    brief = j.objective(out["brief_id"])
    assert brief["source"] == "repro" and brief["check_spec"]["repro"]["sha256"] == repro.test_sha(REPRO)
    assert brief["check_spec"]["files"] == ["backend/syrax/calc.py", TEST] and "return a + b" in brief["goal"]
    verdict, ev = judge(j, o, task)
    assert verdict == "DONE"
    kept, contract = contracts.assess(j, o, task, verdict, ev, "task")
    assert kept == "DONE" and contract["attribution"] == "own"
    assert repro.harvest(j, o, task, root)["event"] == "repro.rejected"  # the same test is filed once


def test_what_a_hunt_left_is_refused_when_it_proves_nothing(tmp_path):
    unbound = REPRO.replace("add(2, 3) == 5", "add(4, 4) == 8")
    root, j, o, task = hunt_with_task(tmp_path, "done", FIX + f"\n# untracked: {TEST}\n" + unbound)
    out = repro.harvest(j, o, task, root)
    assert out["event"] == "repro.rejected" and "quotes none of the evidence" in out["reason"]
    assert judge(j, o, task)[0] == "RETRY"
    new_name = "from syrax.calc import add, total\n\n\ndef test_total():\n    assert total(add(2, 3) == 5) is True\n"
    root, j, o, task = hunt_with_task(tmp_path / "c", "added total()", FIX.replace("+    return a + b", "+    return a + b\n+\n+\n+def total(x):\n+    return True")
                                      + f"\n# untracked: {TEST}\n" + new_name)
    out = repro.harvest(j, o, task, root)
    assert out["event"] == "repro.rejected" and out["verdict"] == "RED_ERROR", out  # red only by importing what the fix adds
    root, j, o, task = hunt_with_task(tmp_path / "b", "NO CODE CAUSE: the model chose the wrong hash", "")
    assert repro.harvest(j, o, task, root)["verdict"] == "NO_CODE_CAUSE"
    assert judge(j, o, task)[0] == "BLOCKED"


def test_a_hunt_never_releases():
    hunt = {"check_spec": {"kind": repro.HUNT_KIND, "signal": "x"}}
    assert "never releases" in repro.release_problems(".", ".", {TEST: "??"}, hunt)[0]


def test_the_cycle_derives_hunts_only_when_enabled(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    monkeypatch.setattr(repro, "derive", lambda journal: calls.append(1) or 0)
    from syrax.test_autonomy import make

    j, core, a = make(tmp_path)
    a.set_enabled(True)
    monkeypatch.setenv("SYRAX_REPRO", "0")
    asyncio.run(a.run_once())
    assert calls == []
    monkeypatch.setenv("SYRAX_REPRO", "1")
    asyncio.run(a.run_once())
    assert calls == [1]


def test_the_snapshot_is_read_back_as_the_diff_and_the_new_files():
    diff, new = repro.parse_snapshot(FIX + f"\n# untracked: {TEST}\n" + REPRO + "\n# untracked: backend/syrax/extra.py\nX = 1\n")
    assert diff == FIX and new == {TEST: REPRO, "backend/syrax/extra.py": "X = 1\n"}
