"""Audit 2026-11-01 (skills S5, live objective #35): skill.verified was journaled under the task that CREATED the skill,
so when a later task re-verified and used it, the objective's check said "the evidence came from elsewhere" and the
objective was BLOCKED. The event now belongs to the task the verification happened in."""

import asyncio

from syrax.test_skills import GOOD, GOOD_TEST, factory


def test_a_later_verification_is_journaled_under_the_later_task(tmp_path):
    j, f, coll = factory(tmp_path)
    first = j.start_task_sync("build word_count")
    f.task_id_provider = lambda: first
    asyncio.run(f.create("word_count", "count words", GOOD, GOOD_TEST))
    later = j.start_task_sync("verify word_count")
    f.task_id_provider = lambda: later
    asyncio.run(f.verify("word_count"))
    verified = [e for e in j.recent_events(200) if e["type"] == "skill.verified"]
    assert [e["task_id"] for e in verified][-2:] == [first, later], [e["task_id"] for e in verified]
    assert j.skill("word_count")["created_task_id"] == first
