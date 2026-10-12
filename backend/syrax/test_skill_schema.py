"""A skill whose arguments a model cannot see is not a working tool (live
2026-10-12: SYRAX built disk_usage with execute(path, top_n) and no
`parameters`; its own tests passed). The factory refuses it at verification and
at boot, and the feature objective it closed opens again."""

import asyncio
from typing import ClassVar

from app.tool.base import BaseTool, ToolResult
from app.tool.tool_collection import ToolCollection
from syrax import catalog
from syrax.journal import Journal
from syrax.skills import SkillFactory, schema_problems

CODE_NO_SCHEMA = """from typing import ClassVar
from app.tool.base import BaseTool, ToolResult


class Skill(BaseTool):
    name: ClassVar[str] = "count_files"
    description: ClassVar[str] = "Counts files in a folder."

    async def execute(self, path: str, limit: int = 10) -> ToolResult:
        import os
        return ToolResult(output=str(min(len(os.listdir(path)), limit)))
"""
CODE_WITH_SCHEMA = CODE_NO_SCHEMA.replace(
    '    description: ClassVar[str] = "Counts files in a folder."\n',
    '    description: ClassVar[str] = "Counts files in a folder."\n'
    '    parameters: ClassVar[dict] = {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}\n',
)
TESTS = """import asyncio
from skills.count_files.skill import Skill


def test_counts(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    assert asyncio.run(Skill().execute(path=str(tmp_path))).output == "1"
"""


class Full(BaseTool):
    name: ClassVar[str] = "full"
    description: ClassVar[str] = "x"
    parameters: ClassVar[dict] = {"type": "object", "properties": {"a": {}, "b": {}}, "required": ["a"]}

    async def execute(self, a: str, b: int = 1, **extra) -> ToolResult:
        return ToolResult(output="ok")


class Missing(Full):
    parameters: ClassVar[dict] = {"type": "object", "properties": {"b": {}}, "required": []}


class NotRequired(Full):
    parameters: ClassVar[dict] = {"type": "object", "properties": {"a": {}, "b": {}}}


def test_the_rule():
    assert schema_problems(Full()) == []
    assert schema_problems(Missing()) == ["execute() takes `a` but `parameters.properties` does not declare it"]
    assert schema_problems(NotRequired()) == ["`a` has no default but is not in `parameters.required`"]


def factory(tmp_path):
    j = Journal(tmp_path / "j.db")
    f = SkillFactory(j, root=tmp_path / "skills", task_id_provider=lambda: None)
    f.attach(ToolCollection())
    return j, f


def test_a_skill_without_a_schema_is_not_registered_and_says_why(tmp_path):
    j, f = factory(tmp_path)
    row = asyncio.run(f.create("count_files", "count files", CODE_NO_SCHEMA, TESTS))
    assert row["status"] == "FAILED" and "count_files" not in f.collection.tool_map
    assert "a model could not call it" in row["evidence"]["evidence"] and "`path`" in row["evidence"]["evidence"]
    row = asyncio.run(f.create("count_files", "count files", CODE_WITH_SCHEMA, TESTS))
    assert row["status"] == "VERIFIED" and "count_files" in f.collection.tool_map


def test_a_verified_skill_without_a_schema_is_demoted_at_boot(tmp_path):
    j, f = factory(tmp_path)
    assert asyncio.run(f.create("count_files", "count files", CODE_WITH_SCHEMA, TESTS))["status"] == "VERIFIED"
    (f.root / "count_files" / "skill.py").write_text(CODE_NO_SCHEMA, encoding="utf-8")  # as an older factory let through
    f2 = SkillFactory(j, root=tmp_path / "skills")
    assert f2.attach(ToolCollection()) == 0 and j.skill("count_files")["status"] == "FAILED"


def test_a_feature_whose_skill_broke_is_opened_again(tmp_path):
    j = Journal(tmp_path / "j.db")
    row = catalog.promote(j, "disk_usage", "catalog")
    j.update_objective_sync(row["id"], status="DONE", evidence={"proof": True})
    j.upsert_skill_sync("disk_usage", "largest files", str(tmp_path), "VERIFIED", evidence={})
    assert catalog.reopen_regressed(j) == []
    j.set_skill_status_sync("disk_usage", "FAILED", note="failed to load at boot: a model could not call it")
    assert catalog.reopen_regressed(j) == [row["id"]]
    o = j.objectives(status="OPEN")[0]
    assert o["id"] == row["id"]
    ev = [e for e in j.recent_events(20) if e["type"] == "objective.reopened"][-1]
    assert "skill `disk_usage` is FAILED now" in ev["payload"]["note"]
    assert catalog.reopen_regressed(j) == []  # open now: nothing to reopen
    assert "declaring every argument of execute() in `parameters`" in catalog.goal_of(catalog.by_id()["disk_usage"])
