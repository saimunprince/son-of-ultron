"""Audit 2026-10-25, "RISE metrics truth": release attempts are gate runs plus refusals (so the
daily ledger publish, which releases without a tool call, counts in both numerator and
denominator), docs-only commits are counted apart, rollbacks are split from end-of-task
cleanups, and the rows the mission names (regressions, repeated failures, human
interventions, cost and latency per verified objective, interruptions resolved) are
computed from a seeded journal with known answers."""

import time

from syrax import journal as jmod
from syrax import rise
from syrax.journal import Journal

DAY = 86400


def seed(tmp_path, monkeypatch):
    now = time.time()
    j = Journal(tmp_path / "j.db")

    def at(ts):
        monkeypatch.setattr(jmod, "_now", lambda: ts)

    def own_task(goal, ts, brain_calls=0):
        at(ts)
        t = j.start_task_sync(goal, kind="autonomous")
        for _ in range(brain_calls):
            j.record_sync("brain.answered", {"event": "answered", "provider": "x", "ms": 10}, task_id=t)
        return t

    def end_task(t, ts, status="SUCCESS"):
        at(ts)
        j.record_sync("final", {"text": "done"}, task_id=t)
        j.record_sync("task.completed", {"status": status, "result": "done"}, task_id=t)

    def gate(t, status):
        j.record_sync("tool.started", {"id": f"r-{t}", "name": "release", "args": {"summary": "x"}}, task_id=t)
        j.record_verification_sync({"status": status, "gates": [], "git_head": "abc"}, task_id=t)
        return j.verifications(limit=1)[0]["id"]

    # ——— the previous window (9 days ago) ———
    p = now - 9 * DAY
    t0 = own_task("[AUTONOMOUS OBJECTIVE] old", p)
    j.record_sync("tool.started", {"id": "r0", "name": "release", "args": {"summary": "x"}}, task_id=t0)
    j.record_sync("tool.failed", {"id": "r0", "name": "release", "ok": False, "output": "Error: release refused: refused: a judge"}, task_id=t0)
    j.record_sync("rollback.created", {"reason": "review rejected the change", "restored": ["a.py"], "removed": [], "snapshot": "s"}, task_id=t0)
    end_task(t0, p + 60)
    j.record_sync("rollback.created", {"reason": rise.CLEANUP_REASON, "restored": ["a.py"], "removed": [], "snapshot": "s", "files": {"a.py": "M"}}, task_id=t0)
    j.add_quality_run_sync([{"id": f"c{i}", "ok": True} for i in range(10)], 100.0, "BASELINE", brain="x")
    i1 = own_task("cut by a restart, never resolved", p + 100)
    j.record_sync("task.interrupted", {"error": "interrupted at step 3", "recovery": {"state": "RESUMABLE"}}, task_id=i1)

    # ——— the last window (1 day ago) ———
    w = now - 1 * DAY
    # objective O1 (change_released): attempt 1 blocked by the gate (5 min, 2 brain calls), attempt 2 landed (15 min, 4 brain calls)
    o1 = j.add_objective_sync("land x", None, 1, "human", {"kind": "change_released"})
    a = own_task("[AUTONOMOUS OBJECTIVE] land x", w, brain_calls=2)
    vid = gate(a, "BLOCKED")
    j.record_sync("rollback.created", {"reason": "verification BLOCKED", "verification_id": vid, "restored": ["backend/syrax/x.py"], "removed": [], "snapshot": "s"}, task_id=a)
    j.record_sync("tool.completed", {"id": f"r-{a}", "name": "release", "ok": True, "output": "RELEASE ROLLED_BACK"}, task_id=a)
    end_task(a, w + 5 * 60)
    j.update_objective_sync(o1["id"], last_task_id=a, bump_attempts=True,
                            progress={"attempts_log": [{"attempt": 1, "task_id": a, "verdict": "RETRY", "strategy": ["str_replace_editor(create x.py)"]}]})
    b = own_task("[AUTONOMOUS OBJECTIVE] land x", w + 10 * 60, brain_calls=4)
    vid = gate(b, "GREEN")
    j.record_sync("commit.created", {"commit": "abc", "files": ["backend/syrax/x.py", "docs/NOTES.md"], "summary": "x", "verification_id": vid}, task_id=b)
    j.record_sync("tool.completed", {"id": f"r-{b}", "name": "release", "ok": True, "output": "RELEASE COMMITTED"}, task_id=b)
    end_task(b, w + 25 * 60)
    j.update_objective_sync(o1["id"], status="DONE", last_task_id=b, bump_attempts=True, evidence={"task_id": b},
                            progress={"attempts_log": [{"attempt": 1, "task_id": a, "verdict": "RETRY", "strategy": ["str_replace_editor(create x.py)"]},
                                                       {"attempt": 2, "task_id": b, "verdict": "DONE", "strategy": ["apply_patch(x.py)", "release(x)"]}]})
    # the daily ledger publish: DevLoop.release called directly, no release tool call, docs only
    led = own_task("[MAINTENANCE] publish the rise ledger (docs/RISE.md) from the journal", w + 30 * 60)
    j.record_verification_sync({"status": "GREEN", "gates": [], "git_head": "abc"}, task_id=led)
    j.record_sync("commit.created", {"commit": "def", "files": ["docs/RISE.md", "docs/DEVLOG.md"], "summary": "docs(rise)", "verification_id": j.verifications(limit=1)[0]["id"]}, task_id=led)
    end_task(led, w + 40 * 60)
    # objective O2 (knowledge_stored): one task of 10 min and 2 brain calls, which asked the human once and left edits behind
    o2 = j.add_objective_sync("learn y", None, 2, "human", {"kind": "knowledge_stored", "topic": "y"})
    c = own_task("[AUTONOMOUS OBJECTIVE] learn y", w + 60 * 60, brain_calls=2)
    j.record_sync("ask", {"question": "may I?"}, task_id=c)
    j.record_sync("answer", {"text": "yes"}, task_id=c)
    j.record_sync("permission.authorized", {"tool": "python_execute", "level": "DESTRUCTIVE", "authorized_by": "human"}, task_id=c)
    j.record_sync("permission.authorized", {"tool": "python_execute", "level": "DESTRUCTIVE", "authorized_by": "goal"}, task_id=c)
    end_task(c, w + 70 * 60)
    j.record_sync("rollback.created", {"reason": rise.CLEANUP_REASON, "restored": [], "removed": ["backend/syrax/_probe.py"], "snapshot": "s", "files": {"backend/syrax/_probe.py": "??"}}, task_id=c)
    j.update_objective_sync(o2["id"], status="DONE", last_task_id=c, bump_attempts=True, evidence={"task_id": c},
                            progress={"attempts_log": [{"attempt": 1, "task_id": c, "verdict": "DONE", "strategy": ["research(y)", "learn(y)"]}]})
    # objective O3 closed on words (task_success): its expensive task must not enter the medians
    o3 = j.add_objective_sync("say hi", None, 3, "human", {"kind": "task_success"})
    d = own_task("[AUTONOMOUS OBJECTIVE] say hi", w + 80 * 60, brain_calls=50)
    end_task(d, w + 200 * 60)
    j.record_sync("rollback.created", {"reason": rise.CLEANUP_REASON, "restored": ["b.py"], "removed": [], "snapshot": "s", "files": {"b.py": "M"}}, task_id=d)
    j.update_objective_sync(o3["id"], status="DONE", last_task_id=d, bump_attempts=True, evidence={"task_id": d})
    # objective O4: two attempts that failed the same way, then a human reopened it
    o4 = j.add_objective_sync("fix z", None, 1, "human", {"kind": "tool_verified", "tool": "z"})
    j.update_objective_sync(o4["id"], bump_attempts=True, progress={"attempts_log": [{"attempt": 1, "task_id": "t-z1", "verdict": "RETRY", "strategy": ["research(z)"]}]})
    j.update_objective_sync(o4["id"], status="BLOCKED", bump_attempts=True,
                            progress={"attempts_log": [{"attempt": 1, "task_id": "t-z1", "verdict": "RETRY", "strategy": ["research(z)"]},
                                                       {"attempt": 2, "task_id": "t-z2", "verdict": "RETRY", "strategy": ["research(z)"]}]})
    j.update_objective_sync(o4["id"], status="OPEN", note="human: the tool exists now, try again")
    # objective O5: machine-checked, closed from existing evidence, no task
    o5 = j.add_objective_sync("tool w verified", None, 3, "human", {"kind": "tool_verified", "tool": "w"})
    j.update_objective_sync(o5["id"], status="DONE", note="closed from existing evidence")
    # quality: a full run passed, a subset re-run regressed
    j.add_quality_run_sync([{"id": f"c{i}", "ok": True} for i in range(10)], 100.0, "PASS", brain="x")
    j.add_quality_run_sync([{"id": "c1", "ok": False}], 0.0, "REGRESSION", brain="x", compared_to=1, delta=-100.0)
    # interruptions: one dismissed by a human, one resumed and finished, one still waiting
    i2 = own_task("cut, then dismissed", w + 300 * 60)
    j.record_sync("task.interrupted", {"error": "interrupted at step 2", "recovery": {"state": "UNCERTAIN"}}, task_id=i2)
    j.record_sync("task.cancelled", {"error": "dismissed by human: superseded"}, task_id=i2)
    i3 = own_task("cut, then resumed", w + 310 * 60)
    j.record_sync("task.interrupted", {"error": "interrupted at step 2", "recovery": {"state": "RESUMABLE"}}, task_id=i3)
    j.record_sync("recovery.resumed", {"boot_id": "b2"}, task_id=i3)
    end_task(i3, w + 320 * 60)
    i4 = own_task("cut, still waiting", w + 330 * 60)
    j.record_sync("task.interrupted", {"error": "interrupted at step 1", "recovery": {"state": "RESUMABLE"}}, task_id=i4)
    j.close()
    monkeypatch.setattr(jmod, "_now", time.time)
    return tmp_path / "j.db", now


def metrics(tmp_path, monkeypatch):
    db, now = seed(tmp_path, monkeypatch)
    data = rise.measure(db, now)
    return {r["id"]: r for r in data["metrics"]}, data


def test_release_attempts_are_gate_runs_plus_refusals_so_the_ledger_publish_counts_on_both_sides(tmp_path, monkeypatch):
    m, _ = metrics(tmp_path, monkeypatch)
    # last window: three gate runs (two through the release tool, one by the ledger publish with no tool call), two commits
    assert m["release_success"]["last"]["detail"] == "2/3" and m["release_success"]["last"]["value"] == 66.7
    # previous window: one release refused before the gate, no gate run, no commit
    assert m["release_success"]["previous"]["detail"] == "0/1" and m["release_success"]["previous"]["value"] == 0.0
    assert m["release_success"]["all"]["detail"] == "2/4"
    assert "verification.completed" in m["release_success"]["definition"] and "ledger" in m["release_success"]["definition"]


def test_commits_that_only_regenerated_docs_are_counted_apart(tmp_path, monkeypatch):
    m, _ = metrics(tmp_path, monkeypatch)
    assert m["own_commits"]["last"]["value"] == 1  # backend/syrax/x.py (+ a doc) landed
    assert m["docs_commits"]["last"]["value"] == 1  # docs/RISE.md, docs/DEVLOG.md only
    assert m["own_commits"]["all"]["value"] == 1 and m["docs_commits"]["all"]["value"] == 1
    assert m["own_commits"]["previous"]["value"] == 0 and m["docs_commits"]["previous"]["value"] == 0


def test_rollbacks_by_the_release_are_split_from_end_of_task_cleanups(tmp_path, monkeypatch):
    m, _ = metrics(tmp_path, monkeypatch)
    assert m["rollbacks"]["last"]["value"] == 1 and m["rollbacks"]["previous"]["value"] == 1  # gate BLOCKED; review rejected
    assert m["cleanups"]["last"]["value"] == 2 and m["cleanups"]["previous"]["value"] == 1
    assert m["rollbacks"]["all"]["value"] + m["cleanups"]["all"]["value"] == 5  # every rollback.created lands in exactly one row
    assert m["rollbacks"]["label"] == "Changes rolled back by the gate or the review"
    assert m["cleanups"]["label"] == "Unreleased edits cleaned up after a task"


def test_regression_rate_counts_quality_runs_that_regressed(tmp_path, monkeypatch):
    m, _ = metrics(tmp_path, monkeypatch)
    assert m["regressions"]["last"]["value"] == 50.0 and m["regressions"]["last"]["detail"] == "1/2"
    assert m["regressions"]["previous"]["value"] == 0.0 and m["regressions"]["all"]["detail"] == "1/3"
    assert m["regressions"]["better"] == "lower"


def test_repeated_failure_rate_reads_the_strategy_fingerprints_of_the_attempts_log(tmp_path, monkeypatch):
    m, _ = metrics(tmp_path, monkeypatch)
    # O1 (two attempts, different strategies) and O4 (two failed attempts, the same strategy) have two or more attempts
    assert m["repeated_failures"]["last"]["detail"] == "1/2" and m["repeated_failures"]["last"]["value"] == 50.0
    assert m["repeated_failures"]["previous"]["value"] is None
    assert "attempts_log" in m["repeated_failures"]["definition"] and "fingerprint" in m["repeated_failures"]["definition"]


def test_human_interventions_count_questions_permissions_objective_edits_and_stops(tmp_path, monkeypatch):
    m, _ = metrics(tmp_path, monkeypatch)
    assert m["human_interventions"]["last"]["value"] == 4
    assert m["human_interventions"]["last"]["detail"] == "1 asked, 1 permissions, 1 objectives, 1 tasks stopped"
    assert m["human_interventions"]["previous"]["value"] == 0  # a permission authorized by the goal is not a human


def test_cost_and_latency_per_verified_objective_are_medians_over_all_their_tasks(tmp_path, monkeypatch):
    m, _ = metrics(tmp_path, monkeypatch)
    # O1: 2 + 4 brain calls over 5 + 15 minutes; O2: 2 calls over 10 minutes; O3 (task_success, 50 calls) and O5 (no task) are out
    assert m["brain_calls_per_objective"]["last"]["value"] == 4 and m["brain_calls_per_objective"]["last"]["detail"] == "median of 2, 1 closed without a task"
    assert m["minutes_per_objective"]["last"]["value"] == 15.0 and m["minutes_per_objective"]["last"]["detail"] == "median of 2, 1 closed without a task"
    assert m["brain_calls_per_objective"]["previous"]["value"] is None and m["minutes_per_objective"]["previous"]["value"] is None
    assert m["brain_calls_per_objective"]["label"] == "Brain calls per verified objective (median)"
    assert m["minutes_per_objective"]["label"] == "Minutes per verified objective (median)"


def test_interrupted_tasks_resumed_or_dismissed_has_a_denominator(tmp_path, monkeypatch):
    m, _ = metrics(tmp_path, monkeypatch)
    assert m["interrupted_resolved"]["last"]["detail"] == "2/3" and m["interrupted_resolved"]["last"]["value"] == 66.7
    assert m["interrupted_resolved"]["previous"]["detail"] == "0/1"
    assert m["interrupted_resolved"]["all"]["detail"] == "2/4" and m["interrupted_resolved"]["better"] == "higher"


def test_the_rendered_ledger_carries_the_new_rows_with_their_definitions(tmp_path, monkeypatch):
    db, now = seed(tmp_path, monkeypatch)
    text = rise.render(rise.measure(db, now), head="abc1234")
    for label in ("Quality runs that regressed", "Objectives that repeated a failed strategy", "Human interventions",
                  "Brain calls per verified objective (median)", "Minutes per verified objective (median)",
                  "Interrupted tasks resumed or dismissed", "Commits that only regenerated docs",
                  "Changes rolled back by the gate or the review", "Unreleased edits cleaned up after a task"):
        assert f"| {label} |" in text and f"- **{label}**:" in text
    assert "| Releases that landed | 66.7 % (2/3) | 0 % (0/1) | 50 % (2/4) | higher | better |" in text
    assert "| Brain calls per verified objective (median) | 4 (median of 2, 1 closed without a task) |" in text
    assert "| Minutes per verified objective (median) | 15 (median of 2, 1 closed without a task) |" in text
    assert "| Interrupted tasks resumed or dismissed | 66.7 % (2/3) | 0 % (0/1) | 50 % (2/4) | higher | better |" in text
