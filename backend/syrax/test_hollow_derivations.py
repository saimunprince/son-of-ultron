"""Measured 2026-10-19: of 243 DONE objectives, 208 changed nothing. Two derivations that fed that: a failed
[MAINTENANCE] task became a web-research objective (objective 299 searched the web for a TypeError raised in
ledger.py, judge code SYRAX may not change), and a quality case that failed twice became a free-form "fix it"
objective (24 of them, none produced a commit; #217 and #283 tried to change the case's own files). The first is
gone; with repro hunts on, the second is left to the hunts (a code cause) and to later runs (the model's choice)."""

from syrax.autonomy import derive_objectives
from syrax.test_autonomy import make

CASE = [{"id": "self_patch_new", "ok": False, "task_id": "t1", "checks": [{"check": "tool release not used", "ok": False}]}]


def test_a_failed_maintenance_task_is_not_researched(tmp_path):
    j, core, a = make(tmp_path, tools=["terminate"])
    t = j.start_task_sync("[MAINTENANCE] publish the rise ledger (docs/RISE.md) from the journal", kind="autonomous")
    j.record_sync("task.failed", {"error": "RISE ledger not published (FAILED): TypeError: unsupported operand at devloop.py:69"}, task_id=t)
    derive_objectives(j, core.selfmodel)
    assert not [o for o in j.objectives(limit=50) if str(o.get("key") or "").startswith("research-failure:")]


def test_with_hunts_on_a_twice_failed_case_gets_no_free_form_objective(tmp_path, monkeypatch):
    j, core, a = make(tmp_path, tools=["terminate"])
    j.add_quality_run_sync(CASE, 0.0, "BASELINE")
    j.add_quality_run_sync(CASE, 0.0, "PASS")
    monkeypatch.setenv("SYRAX_REPRO", "1")
    derive_objectives(j, core.selfmodel)
    assert not [o for o in j.objectives(limit=50) if str(o.get("key") or "").startswith("quality-case:")]
    monkeypatch.setenv("SYRAX_REPRO", "0")
    derive_objectives(j, core.selfmodel)
    assert [o for o in j.objectives(limit=50) if str(o.get("key") or "").startswith("quality-case:self_patch_new:")]
