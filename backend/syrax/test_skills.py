"""Skill factory tests: tests decide registration; failures keep evidence;
VERIFIED skills come back after a restart; removal unregisters."""

import asyncio
import json

import pytest

from app.tool.tool_collection import ToolCollection

from syrax.journal import Journal
from syrax.skills import SkillCreateTool, SkillFactory, SkillListTool, SkillTestTool, load_skill, run_skill_tests

GOOD = '''
from app.tool.base import BaseTool, ToolResult


class Skill(BaseTool):
    name: str = "word_count"
    description: str = "Count words in a text."
    parameters: dict = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}

    async def execute(self, text: str) -> ToolResult:
        return ToolResult(output=str(len(text.split())))
'''
GOOD_TEST = '''
import asyncio
from skills.word_count.skill import Skill


def test_counts_words():
    assert asyncio.run(Skill().execute(text="a b c")).output == "3"


def test_empty():
    assert asyncio.run(Skill().execute(text="")).output == "0"
'''
BAD_TEST = GOOD_TEST.replace('== "3"', '== "4"')
BROKEN_CODE = GOOD.replace("return ToolResult", "return ToolResult(")
WRONG_NAME = GOOD.replace('"word_count"', '"other_name"')


def factory(tmp_path):
    j = Journal(tmp_path / "j.db")
    f = SkillFactory(j, root=tmp_path / "skills", task_id_provider=lambda: None)
    coll = ToolCollection()
    f.attach(coll)
    return j, f, coll


def run(coro):
    return asyncio.run(coro)


def test_verified_skill_is_registered_and_callable(tmp_path):
    j, f, coll = factory(tmp_path)
    row = run(f.create("word_count", "count words", GOOD, GOOD_TEST, dependencies=[], known_limitations=["ascii only"]))
    assert row["status"] == "VERIFIED" and row["tests_passed"] == 2 and row["tests_failed"] == 0 and row["version"] == 1
    assert "word_count" in coll.tool_map and f.loaded["word_count"] is coll.tool_map["word_count"]
    out = run(coll.execute(name="word_count", tool_input={"text": "one two"}))
    assert out.output == "2"
    meta = json.loads((tmp_path / "skills" / "word_count" / "skill.json").read_text())
    assert meta["status"] == "VERIFIED" and meta["known_limitations"] == ["ascii only"] and meta["last_verified"]
    kinds = [e["type"] for e in j.recent_events()]
    assert kinds == ["skill.created", "skill.verified"]
    assert f.list()[0]["registered"] is True


def test_failing_tests_keep_the_skill_out_with_evidence(tmp_path):
    j, f, coll = factory(tmp_path)
    row = run(f.create("word_count", "count words", GOOD, BAD_TEST))
    assert row["status"] == "FAILED" and row["tests_failed"] == 1 and row["tests_passed"] == 1
    assert "word_count" not in coll.tool_map
    assert "assert" in row["evidence"]["evidence"] and row["evidence"]["stage"] == "test"
    assert (tmp_path / "skills" / "word_count" / "skill.py").exists()  # kept for repair
    assert j.recent_events()[-1]["type"] == "skill.failed"
    # repair: same name, tests now pass → version 2, registered
    row = run(f.create("word_count", "count words", GOOD, GOOD_TEST))
    assert row["status"] == "VERIFIED" and row["version"] == 2 and "word_count" in coll.tool_map


def test_syntax_error_and_wrong_name_are_failures(tmp_path):
    j, f, coll = factory(tmp_path)
    row = run(f.create("word_count", "x", BROKEN_CODE, GOOD_TEST))
    assert row["status"] == "FAILED" and row["evidence"]["stage"] == "compile"
    row = run(f.create("word_count", "x", WRONG_NAME, GOOD_TEST))
    assert row["status"] == "FAILED" and row["evidence"]["stage"] in ("test", "load")
    assert "word_count" not in coll.tool_map


def test_create_validation(tmp_path):
    j, f, coll = factory(tmp_path)
    coll.add_tool(SkillListTool())  # a built-in name
    with pytest.raises(ValueError, match="name must match"):
        run(f.create("Bad Name", "x", GOOD, GOOD_TEST))
    with pytest.raises(ValueError, match="built-in"):
        run(f.create("skill_list", "x", GOOD, GOOD_TEST))
    with pytest.raises(ValueError, match="tests"):
        run(f.create("word_count", "x", GOOD, ""))
    with pytest.raises(ValueError, match="class Skill"):
        run(f.create("word_count", "x", "print(1)", GOOD_TEST))
    with pytest.raises(ValueError, match="test_"):
        run(f.create("word_count", "x", GOOD, "x = 1"))
    with pytest.raises(ValueError, match="purpose"):
        run(f.create("word_count", " ", GOOD, GOOD_TEST))
    with pytest.raises(ValueError, match="no skill"):
        run(f.verify("ghost"))
    with pytest.raises(ValueError, match="no skill"):
        run(f.remove("ghost"))


def test_verified_skills_survive_restart_and_broken_ones_are_demoted(tmp_path):
    j, f, coll = factory(tmp_path)
    run(f.create("word_count", "count words", GOOD, GOOD_TEST))
    j.close()
    j2 = Journal(tmp_path / "j.db")
    f2 = SkillFactory(j2, root=tmp_path / "skills")
    coll2 = ToolCollection()
    assert f2.attach(coll2) == 1 and "word_count" in coll2.tool_map
    # the file rots on disk between boots → not VERIFIED any more
    (tmp_path / "skills" / "word_count" / "skill.py").write_text("this is not python (")
    f3 = SkillFactory(j2, root=tmp_path / "skills")
    coll3 = ToolCollection()
    assert f3.attach(coll3) == 0 and "word_count" not in coll3.tool_map
    assert j2.skill("word_count")["status"] == "FAILED"


def test_remove_unregisters_and_retest_updates_status(tmp_path):
    j, f, coll = factory(tmp_path)
    run(f.create("word_count", "count words", GOOD, GOOD_TEST))
    row = run(f.remove("word_count"))
    assert row["status"] == "DISABLED" and "word_count" not in coll.tool_map
    (tmp_path / "skills" / "word_count" / "test_skill.py").write_text(BAD_TEST)
    row = run(f.verify("word_count"))
    assert row["status"] == "FAILED" and row["version"] == 2
    (tmp_path / "skills" / "word_count" / "test_skill.py").write_text(GOOD_TEST)
    row = run(f.verify("word_count"))
    assert row["status"] == "VERIFIED" and "word_count" in coll.tool_map


def test_run_skill_tests_reports_missing_and_timeouts(tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    r = run_skill_tests(d)
    assert r["status"] == "FAILED" and "missing" in r["evidence"]
    (d / "skill.py").write_text("x = 1\n")
    (d / "test_skill.py").write_text("import time\n\ndef test_slow():\n    time.sleep(5)\n")
    r = run_skill_tests(d, timeout=1.0)
    assert r["status"] == "FAILED" and "timed out" in r["evidence"]
    (d / "test_skill.py").write_text("def test_ok():\n    assert True\n")
    r = run_skill_tests(d)
    assert r["status"] == "VERIFIED" and r["passed"] == 1
    with pytest.raises(ImportError):
        load_skill(d)  # no Skill class


def test_tools_report_and_refuse_without_factory(tmp_path):
    assert run(SkillCreateTool().execute(name="a", purpose="b", code="c", test_code="d")).error
    assert run(SkillListTool().execute()).error
    assert run(SkillTestTool().execute(name="a")).error
    j, f, coll = factory(tmp_path)
    create, lst, test = SkillCreateTool(), SkillListTool(), SkillTestTool()
    create.factory = lst.factory = test.factory = f
    assert "No skills" in run(lst.execute()).output
    out = run(create.execute(name="word_count", purpose="count words", code=GOOD, test_code=BAD_TEST))
    assert not out.error and "FAILED" in out.output and "Not registered" in out.output and "assert" in out.output
    out = run(create.execute(name="word_count", purpose="count words", code=GOOD, test_code=GOOD_TEST))
    assert "VERIFIED" in out.output and "registered" in out.output
    assert "word_count v2 VERIFIED (registered)" in run(lst.execute()).output
    assert "VERIFIED" in run(test.execute(name="word_count")).output
    assert "disabled" in run(test.execute(name="word_count", action="remove")).output
    assert run(test.execute(name="ghost")).error
    assert "refused" in run(create.execute(name="9bad", purpose="x", code=GOOD, test_code=GOOD_TEST)).error
