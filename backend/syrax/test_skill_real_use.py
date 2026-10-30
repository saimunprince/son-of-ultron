"""Audit 2026-10-29 (capability acquisition): a skill_verified objective closed as soon as the skill passed its own
tests, which the same brain wrote with the code, so nothing ever showed that the new capability did its job. It now
also needs one real call of the skill after its verification, and that call must succeed. The brief says so, and asks
to look for an existing skill and to research how it is done before building."""

from syrax.autonomy import BRIEF_HINTS, judge
from syrax.journal import Journal


def setup(tmp_path):
    j = Journal(tmp_path / "j.db")
    o = j.add_objective_sync("build weather_now", source="human", check={"kind": "skill_verified", "name": "weather_now"})
    d = tmp_path / "skills" / "weather_now"
    d.mkdir(parents=True)
    (d / "skill.py").write_text("x")
    j.upsert_skill_sync("weather_now", "current weather", str(d), "VERIFIED")
    return j, o


def call(j, ok):
    t = j.start_task_sync("weather in Dhaka now")
    j.record_sync("tool.started", {"id": "c", "name": "weather_now", "args": {"city": "Dhaka"}}, task_id=t)
    j.record_sync("tool.completed" if ok else "tool.failed", {"id": "c", "name": "weather_now", "ok": ok, "output": "x"}, task_id=t)


def test_tests_alone_do_not_close_it(tmp_path):
    j, o = setup(tmp_path)
    verdict, ev = judge(j, o, None)
    assert verdict == "RETRY" and ev["missing"].startswith("one real, successful call")


def test_a_failed_real_call_does_not_close_it_and_a_successful_one_does(tmp_path):
    j, o = setup(tmp_path)
    call(j, ok=False)
    assert judge(j, o, None)[0] == "RETRY"
    call(j, ok=True)
    assert judge(j, o, None)[0] == "DONE"


def test_the_spec_may_waive_it(tmp_path):
    j = Journal(tmp_path / "j.db")
    o = j.add_objective_sync("build x", source="human", check={"kind": "skill_verified", "name": "x", "real_use": False})
    d = tmp_path / "skills" / "x"
    d.mkdir(parents=True)
    (d / "skill.py").write_text("x")
    j.upsert_skill_sync("x", "x", str(d), "VERIFIED")
    assert judge(j, o, None)[0] == "DONE"


def test_the_brief_says_look_first_research_then_build_then_call_it():
    hint = BRIEF_HINTS["skill_verified"]
    assert hint.index("skill_list") < hint.index("research") < hint.index("skill_create") < hint.index("one real call")
