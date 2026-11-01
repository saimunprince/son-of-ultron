"""Audit 2026-11-01 (skills S9): skill_test on code edited on disk kept no version, so when the edit broke the tests
the verified code was gone and nothing could be rolled back to. The sources as last verified are kept beside the
skill (.verified) and moved to .versions/<code_version> before such a retest; skill_rollback brings them back."""

import asyncio

from syrax.skills import VERIFIED_COPY, content_hash
from syrax.test_skills import GOOD, GOOD_TEST, factory


def test_a_broken_disk_edit_can_be_rolled_back_to_the_verified_code(tmp_path):
    j, f, coll = factory(tmp_path)
    row = asyncio.run(f.create("word_count", "count words", GOOD, GOOD_TEST))
    skill_dir = tmp_path / "skills" / "word_count"
    verified_hash = row["content_hash"]
    assert content_hash(skill_dir / VERIFIED_COPY) == verified_hash
    (skill_dir / "skill.py").write_text(GOOD.replace("str(len(text.split()))", "'-998'"))  # an edit that breaks it
    failed = asyncio.run(f.verify("word_count"))
    assert failed["status"] == "FAILED"
    assert row["code_version"] in f.kept_versions("word_count")
    assert [e for e in j.recent_events(100) if e["type"] == "skill.version_kept"]
    back = asyncio.run(f.rollback("word_count"))
    assert back["status"] == "VERIFIED" and content_hash(skill_dir) == verified_hash
    assert asyncio.run(coll.execute(name="word_count", tool_input={"text": "a b"})).output == "2"


def test_an_unchanged_skill_keeps_no_extra_version(tmp_path):
    j, f, coll = factory(tmp_path)
    asyncio.run(f.create("word_count", "count words", GOOD, GOOD_TEST))
    asyncio.run(f.verify("word_count"))
    assert f.kept_versions("word_count") == []
