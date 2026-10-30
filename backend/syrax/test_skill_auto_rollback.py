"""Audit 2026-10-29 (capability acquisition, "no automatic rollback"): a skill whose new version kept failing in real use
waited for the human's skill_rollback even when the version before it had worked. The autonomy cycle now measures that
regression from the journal (skillevo.regressions) and, at level 3 and up, rolls the skill back to its kept version
(reversible: the replaced code is kept), journaling skill.regression first."""

import asyncio
import time

from syrax import autonomy as auto
from syrax import skillevo
from syrax.test_autonomy import make
from syrax.test_skills import GOOD, GOOD_TEST, factory  # noqa: F401

V2 = GOOD.replace("str(len(text.split()))", "str(len(text.split()) + 0)")


def calls(j, ok, n=3):
    for i in range(n):
        t = j.start_task_sync(f"count words {i}")
        j.record_sync("tool.started", {"id": f"c{i}", "name": "word_count", "args": {"text": "a b"}}, task_id=t)
        j.record_sync("tool.completed" if ok else "tool.failed",
                      {"id": f"c{i}", "name": "word_count", "ok": ok, "output": "2" if ok else "Error: boom"}, task_id=t)
        time.sleep(0.01)


def setup(tmp_path, v1_ok=True):
    j, f, coll = factory(tmp_path)
    assert asyncio.run(f.create("word_count", "count words", GOOD, GOOD_TEST))["status"] == "VERIFIED"
    calls(j, ok=v1_ok)
    time.sleep(0.02)
    assert asyncio.run(f.create("word_count", "count words", V2, GOOD_TEST))["code_version"] == 2
    calls(j, ok=False)
    return j, f


def test_a_new_version_that_fails_where_the_old_one_worked_is_a_regression(tmp_path):
    j, f = setup(tmp_path)
    (r,) = skillevo.regressions(j, f.kept_versions)
    assert r["skill"] == "word_count" and r["current"]["failures"] == 3 and r["previous"] == {"uses": 3, "failures": 0, "code_version": 1}


def test_no_regression_when_the_old_version_failed_too(tmp_path):
    j, f = setup(tmp_path, v1_ok=False)
    assert skillevo.regressions(j, f.kept_versions) == []


def test_the_cycle_rolls_it_back_at_level_3_and_not_below(tmp_path, monkeypatch):
    j, f = setup(tmp_path)
    _, core, a = make(tmp_path / "auto")
    a.journal = j
    core.journal = j
    core.skills = f
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    a.set_level(2)
    asyncio.run(a._roll_back_regressions())
    assert "+ 0" in (f.root / "word_count" / "skill.py").read_text()  # level 2: untouched
    a.set_level(3)
    asyncio.run(a._roll_back_regressions())
    assert "+ 0" not in (f.root / "word_count" / "skill.py").read_text()  # the kept version 1 is live again
    kinds = [e["type"] for e in j.recent_events(50)]
    assert kinds.index("skill.regression") < kinds.index("skill.rolled_back")
    assert j.skill("word_count")["status"] == "VERIFIED" and f.kept_versions("word_count") == [2]  # v2 kept: reversible
