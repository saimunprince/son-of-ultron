"""Audit 2026-11-01 (skills S2, live 2026-10-30): a revision of organize_folder went from 5 tests to 3, and the two it
dropped were its file-safety tests; the revision was VERIFIED. A revision that drops a test the live version has is
refused now; the live version stays; adding tests is fine."""

import asyncio

from syrax.skills import skill_test_names
from syrax.test_skill_candidate import SHOUT, SHOUT_TEST
from syrax.test_skills import GOOD, GOOD_TEST, factory


def test_a_revision_that_drops_a_test_is_refused_and_the_live_version_stays(tmp_path):
    j, f, coll = factory(tmp_path)
    live = asyncio.run(f.create("word_count", "count words", GOOD, GOOD_TEST))
    names = skill_test_names(tmp_path / "skills" / "word_count" / "test_skill.py")
    assert len(names) >= 2
    keep_one = sorted(names)[0]
    # a candidate test file that keeps only one of the live tests
    lines, kept, skip = [], [], False
    for line in SHOUT_TEST.splitlines():
        if line.startswith("def test"):
            skip = not line.startswith(f"def {keep_one}(")
        if not skip:
            kept.append(line)
    row = asyncio.run(f.create("word_count", "count words", SHOUT, "\n".join(kept) + "\n"))
    assert row.get("revision_failed") and row["evidence"]["stage"] == "tests_dropped", row
    assert (tmp_path / "skills" / "word_count" / "skill.py").read_text() == GOOD
    assert asyncio.run(coll.execute(name="word_count", tool_input={"text": "a b"})).output == "2"


def test_a_revision_that_keeps_and_adds_tests_goes_through(tmp_path):
    j, f, coll = factory(tmp_path)
    asyncio.run(f.create("word_count", "count words", GOOD, GOOD_TEST))
    extra = SHOUT_TEST + "\n\ndef test_extra_case():\n    assert 1 == 1\n"
    row = asyncio.run(f.create("word_count", "count words", SHOUT, extra))
    assert row["status"] == "VERIFIED" and not row.get("revision_failed")
