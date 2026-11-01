"""Audit 2026-11-01 (skills S6, live objectives 27, 33, 37): the skill_verified check needed the skill verified AFTER
the objective was set, so a follow-up for a skill already verified and in use stayed RETRY and was BLOCKED. An
earlier verification counts once a real successful call comes after the objective was set."""

import time

from syrax.autonomy import judge
from syrax.journal import Journal


def test_a_skill_verified_before_the_objective_closes_it_on_a_later_real_call(tmp_path):
    j = Journal(tmp_path / "j.db")
    d = tmp_path / "skills" / "image_tools"
    d.mkdir(parents=True)
    (d / "skill.py").write_text("x")
    j.upsert_skill_sync("image_tools", "resize images", str(d), "VERIFIED")
    t = j.start_task_sync("resize")
    j.record_sync("tool.started", {"id": "a", "name": "image_tools", "args": {}}, task_id=t)
    j.record_sync("tool.completed", {"id": "a", "name": "image_tools", "ok": True, "output": "ok"}, task_id=t)
    time.sleep(0.01)
    o = j.add_objective_sync("verify image_tools", None, 2, "selfmodel", {"kind": "skill_verified", "name": "image_tools"})
    verdict, ev = judge(j, j.objective(o["id"]), None)
    assert verdict == "RETRY" and "after this objective was set" in ev["missing"]  # an old call is not this objective's
    time.sleep(0.01)
    j.record_sync("tool.started", {"id": "b", "name": "image_tools", "args": {}}, task_id=t)
    j.record_sync("tool.completed", {"id": "b", "name": "image_tools", "ok": True, "output": "ok"}, task_id=t)
    verdict, ev = judge(j, j.objective(o["id"]), None)
    assert verdict == "DONE" and ev["real_use_ok"]
