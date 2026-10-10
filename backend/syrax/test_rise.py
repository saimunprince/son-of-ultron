"""The rise ledger counts what the journal shows, per window, and nothing else."""

import time

from syrax import journal as jmod
from syrax import rise
from syrax.devloop import JUDGES
from syrax.journal import Journal
from syrax.selfmodel import PRINCIPLES

DAY = 86400


def seed(tmp_path, monkeypatch):
    now = time.time()
    j = Journal(tmp_path / "j.db")

    def at(ts):
        monkeypatch.setattr(jmod, "_now", lambda: ts)

    # the previous window (8-10 days ago): one release that failed, one false claim, a weak closure
    at(now - 9 * DAY)
    t = j.start_task_sync("[AUTONOMOUS OBJECTIVE] improve release", kind="autonomous")
    j.record_sync("tool.started", {"id": "r1", "name": "release", "args": {"summary": "x"}}, task_id=t)
    j.record_sync("tool.failed", {"id": "r1", "name": "release", "ok": False,
                                  "output": "Error: release refused: refused: backend/syrax/quality.py: this file judges SYRAX's own work"}, task_id=t)
    j.record_sync("final", {"text": "The release limitation has been addressed."}, task_id=t)
    j.record_sync("task.completed", {"status": "SUCCESS", "result": "The release limitation has been addressed."}, task_id=t)
    weak = j.add_objective_sync("say hi", None, 3, "human", None)
    j.update_objective_sync(weak["id"], status="DONE", bump_attempts=True)
    j.add_quality_run_sync([{"id": f"c{i}", "ok": i < 8} for i in range(10)], 80.0, "BASELINE", brain="x")

    # the last window (1-2 days ago): a release that landed, a full quality run, a machine-checked objective
    at(now - 1 * DAY)
    t = j.start_task_sync("[AUTONOMOUS OBJECTIVE] land the probe", kind="autonomous")
    j.record_sync("tool.started", {"id": "e1", "name": "str_replace_editor", "args": {"command": "create", "path": "x"}}, task_id=t)
    j.record_sync("tool.completed", {"id": "e1", "name": "str_replace_editor", "ok": True, "output": "ok"}, task_id=t)
    j.record_sync("code.changed", {"path": "backend/syrax/x.py", "command": "create"}, task_id=t)
    j.record_sync("tool.started", {"id": "r2", "name": "release", "args": {"summary": "probe"}}, task_id=t)
    j.record_sync("tool.completed", {"id": "r2", "name": "release", "ok": True, "output": "RELEASE COMMITTED"}, task_id=t)
    j.record_sync("commit.created", {"commit": "abc", "files": ["backend/syrax/x.py"], "summary": "probe", "verification_id": 1}, task_id=t)
    j.record_sync("final", {"text": "I have fixed the probe and released it."}, task_id=t)  # a claim, but backed by a change
    j.record_sync("task.completed", {"status": "SUCCESS", "result": "I have fixed the probe and released it."}, task_id=t)
    o = j.add_objective_sync("land the probe", None, 1, "human", {"kind": "change_released"})
    j.update_objective_sync(o["id"], status="DONE", bump_attempts=True)
    j.add_quality_run_sync([{"id": f"c{i}", "ok": True} for i in range(10)], 100.0, "PASS", brain="x")
    j.add_quality_run_sync([{"id": "c1", "ok": False}], 0.0, "REGRESSION", brain="x")  # a subset re-run is not the suite
    j.record_verification_sync({"status": "GREEN", "gates": [], "git_head": "abc"})
    j.close()
    monkeypatch.setattr(jmod, "_now", time.time)
    return tmp_path / "j.db", now


def test_the_ledger_counts_each_window_from_the_journal(tmp_path, monkeypatch):
    db, now = seed(tmp_path, monkeypatch)
    data = rise.measure(db, now)
    m = {r["id"]: r for r in data["metrics"]}
    assert m["quality"]["last"]["value"] == 100.0 and m["quality"]["previous"]["value"] == 80.0  # the 1-case subset is skipped
    assert trend(m["quality"]) == "better"
    assert m["own_commits"]["last"]["value"] == 1 and m["own_commits"]["previous"]["value"] == 0
    assert m["release_success"]["last"]["value"] == 100.0 and m["release_success"]["previous"]["value"] == 0.0
    assert m["release_success"]["all"]["detail"] == "1/2"
    assert m["unbacked_claims"]["previous"]["value"] == 1  # "has been addressed", nothing changed
    assert m["unbacked_claims"]["last"]["value"] == 0  # "I have fixed", and the task did change code
    assert m["weak_closures"]["previous"]["value"] == 100.0 and m["weak_closures"]["last"]["value"] == 0.0
    assert m["objective_success"]["last"]["value"] == 100.0 and m["objective_success"]["previous"]["value"] is None
    assert m["guard_refusals"]["previous"]["value"] == 1 and m["gate_green"]["last"]["value"] == 100.0
    assert m["experiments"]["all"]["value"] == 0


def trend(row):
    return rise.trend(row)


def test_render_has_every_pillar_and_reports_missing_evidence_as_a_dash(tmp_path, monkeypatch):
    db, now = seed(tmp_path, monkeypatch)
    text = rise.render(rise.measure(db, now), head="abc1234")
    for pillar in rise.PILLARS:
        assert f"## {pillar}" in text
    assert "| Machine-checked objectives done | 100 % (1/1) | — |" in text
    assert "nothing here is typed by hand" in text and "`abc1234`" in text
    assert all(m.definition for m in rise.METRICS) and {m.pillar for m in rise.METRICS} == set(rise.PILLARS)


def test_the_ledger_never_writes_the_journal(tmp_path, monkeypatch):
    db, now = seed(tmp_path, monkeypatch)
    before = db.read_bytes()
    rise.measure(db, now)
    assert db.read_bytes() == before


def test_what_measures_syrax_is_out_of_its_own_reach():
    assert "backend/syrax/rise.py" in JUDGES and "backend/syrax/capmatrix.py" in JUDGES


def test_the_principle_is_part_of_its_identity():
    assert any("Demonstrate it" in p and "Let the evidence speak" in p for p in PRINCIPLES)
