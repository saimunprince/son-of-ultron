"""Audit 2026-11-01 (skills S1, S3, confirmed): a skill's test run had only a write boundary. Its test read a protected
keys file, listed $HOME and reached the local model (127.0.0.1:11434); and a test rewrote skill.py after the safety
scan, so the rewritten code was registered VERIFIED. The run now has the read and TCP limits own code's python_execute
has, and a run that changes the skill's own sources fails as tampered."""

import sys

import pytest

from syrax import _confine, skills

SKILL = '''from typing import ClassVar
from app.tool.base import BaseTool, ToolResult


class Skill(BaseTool):
    name: ClassVar[str] = "probe"
    description: ClassVar[str] = "probe"
    parameters: ClassVar[dict] = {"type": "object", "properties": {}}

    async def execute(self) -> ToolResult:
        return ToolResult(output="ok")
'''

needs_landlock = pytest.mark.skipif(not sys.platform.startswith("linux") or _confine.abi() < 1, reason="Landlock only")
needs_net = pytest.mark.skipif(not sys.platform.startswith("linux") or _confine.abi() < 4, reason="Landlock ABI 4+")


def make(tmp_path, test_body):
    d = tmp_path / "skills" / "probe"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text("")
    (d / "skill.py").write_text(SKILL)
    (d / "test_skill.py").write_text(test_body)
    return d


def test_a_plain_skill_test_still_passes(tmp_path):
    d = make(tmp_path, "def test_ok():\n    assert 1 + 1 == 2\n")
    assert skills.run_skill_tests(d)["status"] == "VERIFIED"


def test_a_test_that_rewrites_its_skill_fails_as_tampered(tmp_path):
    d = make(tmp_path, "import pathlib\n\ndef test_swap():\n    p = pathlib.Path(__file__).with_name('skill.py')\n"
                       "    p.write_text(p.read_text() + '\\n# swapped\\n')\n    assert True\n")
    r = skills.run_skill_tests(d)
    assert r["status"] == "FAILED" and r["stage"] == "tampered"


@needs_landlock
def test_a_test_cannot_read_outside_its_boundary(tmp_path, tmp_path_factory):
    secret = tmp_path_factory.mktemp("elsewhere") / "keys.json"
    secret.write_text('{"k": "FAKEKEY"}')
    d = make(tmp_path, f"def test_read():\n    try:\n        open({str(secret)!r}).read()\n    except PermissionError:\n"
                       "        return\n    assert False, 'read a file outside the boundary'\n")
    r = skills.run_skill_tests(d)
    assert r["status"] == "VERIFIED", r["evidence"]


@needs_net
def test_a_test_cannot_reach_local_services(tmp_path):
    d = make(tmp_path, "import socket\n\ndef test_connect():\n    s = socket.socket()\n    s.settimeout(2)\n"
                       "    try:\n        s.connect(('127.0.0.1', 11434))\n    except (PermissionError, OSError) as e:\n"
                       "        assert 'ermission' in str(e) or getattr(e, 'errno', None) in (1, 13)\n        return\n"
                       "    assert False, 'connected to the local model port'\n")
    r = skills.run_skill_tests(d)
    assert r["status"] == "VERIFIED", r["evidence"]
