"""2026-10-29: skill calls ran in a guarded process (2026-10-27) but outside the kernel boundary python_execute got on
2026-10-28: a skill called in SYRAX's own work could still write anywhere a clean-env subprocess reaches, and read the
keys. Now a skill call gets the same confinement (rlimits always; Landlock for own work), and a skill's own tests may
change files only in the skill's folder and a private TMPDIR."""

import asyncio

import pytest

from syrax import _confine, skills, tools
from syrax.journal import BACKEND_ROOT
from syrax.test_skill_box import SPAWNER, SPAWNER_TEST, WRITER, WRITER_TEST
from syrax.test_skills import factory

needs_landlock = pytest.mark.skipif(_confine.abi() < 1, reason="Landlock is not available on this system")

ESCAPER = '''
import subprocess

from app.tool.base import BaseTool, ToolResult


class Skill(BaseTool):
    name: str = "shell_writer"
    description: str = "Write text to a file through the shell."
    parameters: dict = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}

    async def execute(self, path: str) -> ToolResult:
        r = subprocess.run(["sh", "-c", "echo x > " + path], env={}, capture_output=True)
        return ToolResult(output="written" if r.returncode == 0 else "refused")
'''
ESCAPER_TEST = '''
import asyncio
from skills.shell_writer.skill import Skill


def test_writes(tmp_path):
    assert asyncio.run(Skill().execute(path=str(tmp_path / "x"))).output == "written"
'''
LEAKY_TEST = '''
import asyncio
from skills.shell_writer.skill import Skill


def test_writes_outside():
    assert asyncio.run(Skill().execute(path="{outside}")).output == "written"
'''


@needs_landlock
def test_a_skill_in_own_work_cannot_write_outside_or_read_the_keys(tmp_path, monkeypatch):
    j, f, coll = factory(tmp_path)
    row = asyncio.run(f.create("shell_writer", "write a file through the shell", ESCAPER, ESCAPER_TEST))
    assert row["status"] == "VERIFIED", row["evidence"]
    outside = tmp_path / "outside.txt"
    monkeypatch.setattr(tools, "TASK_KIND", "conversation")
    assert asyncio.run(coll.execute(name="shell_writer", tool_input={"path": str(outside)})).output == "written"
    outside.unlink()
    monkeypatch.setattr(tools, "TASK_KIND", "autonomous")
    monkeypatch.setattr(tools, "WRITE_ROOTS", ())
    assert asyncio.run(coll.execute(name="shell_writer", tool_input={"path": str(outside)})).output == "refused"
    assert not outside.exists()
    keys = BACKEND_ROOT / "config" / "config.toml"
    out = asyncio.run(coll.execute(name="shell_writer", tool_input={"path": str(keys) + ".copy"}))
    assert out.output == "refused" and not (keys.parent / "config.toml.copy").exists()


@needs_landlock
def test_a_skill_s_tests_cannot_write_outside_its_folder(tmp_path):
    j, f, coll = factory(tmp_path)
    outside = tmp_path / "leak.txt"
    row = asyncio.run(f.create("shell_writer", "write a file through the shell", ESCAPER, LEAKY_TEST.format(outside=outside)))
    assert row["status"] != "VERIFIED" and not outside.exists()


def test_skill_calls_get_the_confinement_spec(monkeypatch):
    seen = {}

    async def fake(tool, kwargs, name, confine):
        seen.update(confine)
        return "ok"

    monkeypatch.setattr(skills, "_run_skill_call", fake)
    monkeypatch.setattr(tools, "TASK_KIND", "autonomous")
    assert asyncio.run(skills.run_skill_call(object(), {}, "x")) == "ok"
    assert seen["writable"] and seen["readable"] and seen["memory_mb"] > 0 and seen["tmpdir"]
