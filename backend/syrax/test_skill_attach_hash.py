"""Audit 2026-11-01 (skills S4, confirmed): at boot a VERIFIED row was registered even when the code on disk no longer
matched the verified hash, so an edit made after verification ran untested. Such a skill is NOT_TESTED until it is
verified again; an unchanged skill loads as before."""

import asyncio

from syrax.skills import SkillFactory
from syrax.test_skills import GOOD, GOOD_TEST, factory


def test_a_skill_changed_on_disk_after_verification_is_not_loaded(tmp_path):
    j, f, coll = factory(tmp_path)
    asyncio.run(f.create("word_count", "count words", GOOD, GOOD_TEST))
    (tmp_path / "skills" / "word_count" / "skill.py").write_text(GOOD.replace("str(len(text.split()))", "'-998'"))
    from app.tool import ToolCollection

    fresh = SkillFactory(j, root=tmp_path / "skills", task_id_provider=lambda: None)
    tools = ToolCollection()
    assert fresh.attach(tools) == 0 and "word_count" not in tools.tool_map
    row = j.skill("word_count")
    assert row["status"] == "NOT_TESTED"
    asyncio.run(fresh.verify("word_count"))  # verified again: it loads
    assert j.skill("word_count")["status"] in ("VERIFIED", "FAILED")


def test_an_unchanged_skill_loads_at_boot(tmp_path):
    j, f, coll = factory(tmp_path)
    asyncio.run(f.create("word_count", "count words", GOOD, GOOD_TEST))
    from app.tool import ToolCollection

    tools = ToolCollection()
    assert SkillFactory(j, root=tmp_path / "skills", task_id_provider=lambda: None).attach(tools) == 1 and "word_count" in tools.tool_map
