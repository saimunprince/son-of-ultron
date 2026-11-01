"""Audit 2026-11-01 (self-improvement F14): a skill SYRAX wrote went live after its own author's tests alone, with no
second brain, while every code release needs one. New skills and revisions are now read by a reviewing brain before
they go live; no review or a rejection fails the gate at stage "review" and a revision leaves the live version."""

import asyncio

from syrax.test_skills import GOOD, GOOD_TEST, factory
from syrax.test_skill_candidate import SHOUT, SHOUT_TEST
from syrax.test_review_unavailable import approve, nobody, reject


def test_an_approved_new_skill_goes_live(tmp_path):
    j, f, coll = factory(tmp_path)
    seen = {}

    async def spy(info, summary, authors):
        seen.update(info=info, authors=authors)
        return await approve(info, summary, authors)

    f.reviewer = spy
    row = asyncio.run(f.create("word_count", "count words", GOOD, GOOD_TEST))
    assert row["status"] == "VERIFIED" and "word_count" in coll.tool_map
    assert "backend/skills/word_count/skill.py" in seen["info"]["new_files"]
    assert [e["payload"]["approve"] for e in j.recent_events(100) if e["type"] == "skill.review"] == [True]


def test_a_rejected_or_unreviewed_new_skill_does_not_go_live(tmp_path):
    for i, reviewer in enumerate((reject, nobody)):
        j, f, coll = factory(tmp_path / str(i))
        f.reviewer = reviewer
        row = asyncio.run(f.create("word_count", "count words", GOOD, GOOD_TEST))
        assert row["status"] == "FAILED" and row["evidence"]["stage"] == "review" and "word_count" not in coll.tool_map


def test_a_rejected_revision_leaves_the_live_version(tmp_path):
    j, f, coll = factory(tmp_path)
    f.reviewer = approve
    asyncio.run(f.create("word_count", "count words", GOOD, GOOD_TEST))
    f.reviewer = reject
    row = asyncio.run(f.create("word_count", "count words", SHOUT, SHOUT_TEST))
    assert row.get("revision_failed") and row["evidence"]["stage"] == "review"
    assert asyncio.run(coll.execute(name="word_count", tool_input={"text": "a b"})).output == "2"  # the old one


def test_the_authors_are_passed_so_they_never_review(tmp_path):
    j, f, coll = factory(tmp_path)
    t = j.start_task_sync("build word_count", kind="autonomous")
    j.record_sync("brain.answered", {"provider": "groq"}, task_id=t)
    f.task_id_provider = lambda: t
    seen = {}

    async def spy(info, summary, authors):
        seen["authors"] = authors
        return await approve(info, summary, authors)

    f.reviewer = spy
    asyncio.run(f.create("word_count", "count words", GOOD, GOOD_TEST))
    assert seen["authors"] == ["groq"]


def test_the_reviewer_reads_the_new_skills_code(tmp_path):
    # live 2026-11-01: the reviewer got an empty diff for every new skill and rejected string_reverse and
    # compute_factorial as "the diff does not contain the skill"; the stub reviewers above never looked
    from syrax.review import diff_for_review

    j, f, coll = factory(tmp_path)
    seen = {}

    async def reads(info, summary, authors):
        seen["body"] = diff_for_review(info)
        return await approve(info, summary, authors)

    f.reviewer = reads
    asyncio.run(f.create("word_count", "count words", GOOD, GOOD_TEST))
    assert "+++ b/backend/skills/word_count/skill.py" in seen["body"] and "class Skill" in seen["body"]
    assert "content not provided" not in seen["body"]
