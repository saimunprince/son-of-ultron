"""Live 2026-11-01: string_reverse, reverse_text and compute_factorial first failed with a pydantic collection error,
"Field 'name' defined on a base class was overridden by a non-annotated attribute": the brain wrote `name = "..."` in
class Skill. That cost a whole gate run and a confusing failure; skill_create now refuses it up front with the fix."""

import pytest

from syrax import skills
from syrax.test_skills import factory, run  # noqa: F401

BAD = '''
from app.tool.base import BaseTool, ToolResult


class Skill(BaseTool):
    name = "bad_fields"
    description = "Says hi."
    parameters: dict = {"type": "object", "properties": {}, "required": []}

    async def execute(self) -> ToolResult:
        return ToolResult(output="hi")
'''
TEST = "def test_ok():\n    assert True\n"


def test_unannotated_fields_are_named_with_the_fix():
    assert skills.unannotated_fields(BAD) == ["name", "description"]
    good = BAD.replace('name = "', 'name: str = "').replace('description = "', 'description: str = "')
    assert skills.unannotated_fields(good) == []
    assert skills.unannotated_fields("class Other:\n    name = 'x'\n") == []  # only class Skill
    assert skills.unannotated_fields("def broken(:\n") == []  # a syntax error is the gate's to report


def test_skill_create_refuses_them_before_any_gate_run(tmp_path):
    j, f, coll = factory(tmp_path)
    with pytest.raises(ValueError, match=r"name: str = .*description"):
        run(f.create("bad_fields", "says hi", BAD, TEST))
    assert j.skill("bad_fields") is None and not (tmp_path / "skills" / "bad_fields").exists()
