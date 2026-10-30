"""EVOLUTION_PLAN wave 4 (direction 99 skill deprecation): a skill that kept failing, or that nobody had called for
months, stayed a live tool the brain could pick. The daily radar now proposes retiring it, once per version; only the
human retires a skill."""

import time

from syrax import skillevo
from syrax.journal import Journal


def skill(j, tmp_path, name, verified_days_ago=0.0):
    d = tmp_path / "skills" / name
    d.mkdir(parents=True)
    (d / "skill.py").write_text("x")
    j.upsert_skill_sync(name, "a skill", str(d), "VERIFIED")
    if verified_days_ago:
        j._db.execute("UPDATE skills SET last_verified=?, updated=? WHERE name=?",
                      (time.time() - verified_days_ago * 86400,) * 2 + (name,))


def calls(j, name, ok, n):
    t = j.start_task_sync(f"use {name}")
    for i in range(n):
        j.record_sync("tool.started", {"id": f"{name}{ok}{i}", "name": name, "args": {}}, task_id=t)
        j.record_sync("tool.completed" if ok else "tool.failed", {"id": f"{name}{ok}{i}", "name": name, "ok": ok, "output": "x"}, task_id=t)


def test_a_failing_or_idle_skill_is_proposed_once(tmp_path):
    j = Journal(tmp_path / "j.db")
    skill(j, tmp_path, "flaky")
    calls(j, "flaky", True, 2)
    calls(j, "flaky", False, 4)
    skill(j, tmp_path, "forgotten", verified_days_ago=90)
    skill(j, tmp_path, "fine")
    calls(j, "fine", True, 6)
    found = {d["skill"]: d["why"] for d in skillevo.deprecations(j)}
    assert set(found) == {"flaky", "forgotten"} and "failed 4 of 6" in found["flaky"] and "not called" in found["forgotten"]
    assert skillevo.propose_deprecations(j) == 2
    assert skillevo.propose_deprecations(j) == 0  # once per version
    props = [e["payload"] for e in j.recent_events(100) if e["type"] == "proposal.created"]
    assert {p["skill"] for p in props} == {"flaky", "forgotten"} and all(p["kind"] == "skill_deprecation" for p in props)
