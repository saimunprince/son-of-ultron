"""Own work never gets an objective to verify or repair a skill it may not call,
even right after a restart, before the agent has declared the skills: the
registry's recorded level decides then (live 2026-10-13: objective 183 asked
own work to verify screen_brightness, a SYSTEM skill)."""

from syrax import permissions
from syrax.autonomy import derive_objectives, own_work_may_not_call
from syrax.test_autonomy import make


def test_the_registry_level_counts_before_the_skills_are_declared(tmp_path, monkeypatch):
    monkeypatch.setattr(permissions, "DECLARED", {})  # a fresh process: nothing declared yet
    j, core, a = make(tmp_path, tools=["screen_brightness", "disk_usage", "terminate"])
    j.upsert_skill_sync("screen_brightness", "brightness", str(tmp_path), "VERIFIED", evidence={"risk": "SYSTEM"})
    j.upsert_skill_sync("disk_usage", "sizes", str(tmp_path), "VERIFIED", evidence={"risk": "READ_ONLY"})
    assert own_work_may_not_call(j, "screen_brightness") and not own_work_may_not_call(j, "disk_usage")
    assert not own_work_may_not_call(j, "desktop")  # built-ins are refined per call
    derive_objectives(j, core.selfmodel)
    keys = {o["key"] for o in j.objectives(limit=50)}
    assert "verify-capability:disk_usage" in keys and not any("screen_brightness" in k for k in keys)
