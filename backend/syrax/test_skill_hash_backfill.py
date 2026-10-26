"""Live 2026-10-26: 17 of 17 skill rows had no content hash. They were verified before skills carried one (the
lifecycle, 2026-10-25) and never re-verified since (a prebuilt skill stays CURRENT). The journal stores a first hash
without a bump, by design, so such a skill's first code change kept code_version 1, and its second change kept the
replaced code under .versions/1 again, overwriting the original. At boot (SkillFactory.attach) a VERIFIED row
without a hash gets the hash of its files on disk, the verified code, and no version moves."""

import asyncio
import sqlite3

from app.tool.tool_collection import ToolCollection

from syrax.skills import SkillFactory, content_hash
from syrax.test_skill_lifecycle import GOOD_V2
from syrax.test_skills import GOOD, GOOD_TEST, factory

GOOD_V3 = GOOD.replace("len(text.split())", "sum(1 for _ in text.split())")


def run(coro):
    return asyncio.run(coro)


def drop_hash(tmp_path, name):
    """The row as a skill verified before 2026-10-25 left it: no content hash."""
    c = sqlite3.connect(tmp_path / "j.db")
    c.execute("UPDATE skills SET content_hash=NULL WHERE name=?", (name,))
    c.commit()
    c.close()


def boot(j, tmp_path):
    f = SkillFactory(j, root=tmp_path / "skills", task_id_provider=lambda: None)
    f.attach(ToolCollection())
    return f


def test_a_verified_skill_without_a_hash_gets_one_at_boot_and_no_version_moves(tmp_path):
    j, f, _ = factory(tmp_path)
    before = run(f.create("word_count", "count words", GOOD, GOOD_TEST))
    drop_hash(tmp_path, "word_count")
    assert j.skill("word_count")["content_hash"] is None
    f2 = boot(j, tmp_path)
    row = j.skill("word_count")
    assert row["content_hash"] == content_hash(tmp_path / "skills" / "word_count") == before["content_hash"]
    assert (row["version"], row["code_version"], row["status"]) == (before["version"], 1, "VERIFIED")
    assert "word_count" in f2.loaded


def test_after_the_backfill_every_change_is_a_code_version_and_the_original_is_kept(tmp_path):
    j, f, _ = factory(tmp_path)
    run(f.create("word_count", "count words", GOOD, GOOD_TEST))
    drop_hash(tmp_path, "word_count")
    f = boot(j, tmp_path)
    assert run(f.create("word_count", "count words", GOOD_V2, GOOD_TEST))["code_version"] == 2
    assert run(f.create("word_count", "count words", GOOD_V3, GOOD_TEST))["code_version"] == 3
    kept = tmp_path / "skills" / "word_count" / ".versions"
    assert (kept / "1" / "skill.py").read_text() == GOOD  # the original survives the second change
    assert (kept / "2" / "skill.py").read_text() == GOOD_V2


def test_a_row_with_a_hash_is_left_as_it_is(tmp_path):
    j, f, _ = factory(tmp_path)
    run(f.create("word_count", "count words", GOOD, GOOD_TEST))
    h = j.skill("word_count")["content_hash"]
    (tmp_path / "skills" / "word_count" / "skill.py").write_text(GOOD_V2)  # changed on disk, not verified
    boot(j, tmp_path)
    assert j.skill("word_count")["content_hash"] == h  # only a verification moves a stored hash


def test_the_journal_backfill_only_fills_an_empty_hash(tmp_path):
    j, f, _ = factory(tmp_path)
    run(f.create("word_count", "count words", GOOD, GOOD_TEST))
    assert j.backfill_skill_hash_sync("word_count", "f" * 64) is False
    drop_hash(tmp_path, "word_count")
    assert j.backfill_skill_hash_sync("word_count", None) is False
    assert j.backfill_skill_hash_sync("word_count", "e" * 64) is True
    assert j.skill("word_count")["content_hash"] == "e" * 64 and j.skill("word_count")["code_version"] == 1
    assert j.backfill_skill_hash_sync("nope", "e" * 64) is False
