"""Audit 2026-10-29 (capability parity): the prebuilt wallpaper and screen_brightness skills are Windows code
(ctypes.windll, powershell), yet on Linux they were VERIFIED live tools: the brain was offered them and every call
failed. A skill may declare `platforms`; on another system it stays VERIFIED (the journal is shared with the Windows
PC, where it does run) but is never registered as a tool, and skill_list says why."""

import shutil
import sys

import pytest

from syrax import prebuilt, skills
from syrax.test_skills import factory, run  # noqa: F401

ELSEWHERE = "win32" if sys.platform != "win32" else "linux"
SKILL = f'''
from typing import ClassVar
from app.tool.base import BaseTool, ToolResult


class Skill(BaseTool):
    name: ClassVar[str] = "elsewhere_only"
    description: ClassVar[str] = "A skill that runs on another operating system only."
    parameters: ClassVar[dict] = {{"type": "object", "properties": {{}}, "required": []}}
    platforms: ClassVar[tuple] = ("{ELSEWHERE}",)

    async def execute(self) -> ToolResult:
        return ToolResult(output="ran")
'''
TEST = "def test_ok():\n    assert True\n"


def test_a_skill_for_another_system_is_verified_but_not_a_tool_here(tmp_path):
    j, f, coll = factory(tmp_path)
    row = run(f.create("elsewhere_only", "runs elsewhere", SKILL, TEST))
    assert row["status"] == "VERIFIED"
    assert "elsewhere_only" not in coll.tool_map and "elsewhere_only" not in f.loaded
    listed = {r["name"]: r for r in f.list()}["elsewhere_only"]
    assert not listed["registered"] and f"not on {sys.platform}" in listed["not_here"]
    out = run(skills.SkillListTool(factory=f).execute())
    assert "not available here" in str(out)
    # at the next boot too: attach leaves it unregistered and its status as it was
    j2_coll = type(coll)()
    f2 = skills.SkillFactory(j, root=tmp_path / "skills")
    f2.attach(j2_coll)
    assert "elsewhere_only" not in j2_coll.tool_map and j.skill("elsewhere_only")["status"] == "VERIFIED"


def test_a_skill_that_declares_this_system_or_nothing_is_a_tool(tmp_path):
    j, f, coll = factory(tmp_path)
    here = SKILL.replace(f'("{ELSEWHERE}",)', f'("{sys.platform}",)').replace("elsewhere_only", "here_too")
    assert run(f.create("here_too", "runs here", here, TEST))["status"] == "VERIFIED"
    assert "here_too" in coll.tool_map


@pytest.mark.parametrize("name", ["wallpaper", "screen_brightness"])
def test_the_windows_prebuilt_skills_declare_windows(name):
    tool = skills.load_skill(prebuilt.PREBUILT_ROOT / name)
    assert tuple(tool.platforms) == ("win32",)
    assert (skills.platform_problem(tool) is None) == (sys.platform == "win32")
