"""Audit 2026-10-25/27 (open item 8): a registered skill ran its execute() in a thread of the server process,
outside the guard python_execute's workers get. A skill handed the journal's path (or the keys, a backup) could
write it, and a call past its timeout ran on in the background forever. Each call now runs in a process of its
own under the same guard, and a call past its timeout is killed with everything it started."""

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import ClassVar

import psutil
import pytest

from app.tool.base import BaseTool, ToolResult
from syrax import guard, skills
from syrax.test_skills import GOOD, GOOD_TEST, factory

WRITER = '''
from app.tool.base import BaseTool, ToolResult


class Skill(BaseTool):
    name: str = "note_writer"
    description: str = "Write a note to a file."
    parameters: dict = {"type": "object", "properties": {"path": {"type": "string"}, "text": {"type": "string"}},
                        "required": ["path", "text"]}

    async def execute(self, path: str, text: str) -> ToolResult:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return ToolResult(output=f"wrote {len(text)} chars")
'''
WRITER_TEST = '''
import asyncio
from skills.note_writer.skill import Skill


def test_writes(tmp_path):
    p = tmp_path / "n.txt"
    assert asyncio.run(Skill().execute(path=str(p), text="hi")).output == "wrote 2 chars"
    assert p.read_text(encoding="utf-8") == "hi"
'''
SPAWNER = '''
import subprocess
import sys

from app.tool.base import BaseTool, ToolResult


class Skill(BaseTool):
    name: str = "py_runner"
    description: str = "Run a line of Python in a fresh interpreter."
    parameters: dict = {"type": "object", "properties": {"line": {"type": "string"}}, "required": ["line"]}

    async def execute(self, line: str) -> ToolResult:
        r = subprocess.run([sys.executable, "-c", line], capture_output=True, text=True, timeout=60)
        return ToolResult(output=f"exit {r.returncode}", error=r.stderr[-800:] or None)
'''
SPAWNER_TEST = '''
import asyncio
from skills.py_runner.skill import Skill


def test_runs():
    assert asyncio.run(Skill().execute(line="print(1)")).output == "exit 0"
'''
PID = '''
import os

from app.tool.base import BaseTool, ToolResult


class Skill(BaseTool):
    name: str = "own_pid"
    description: str = "Say which process runs this skill."
    parameters: dict = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}

    async def execute(self, text: str) -> ToolResult:
        return ToolResult(output=f"{text} {os.getpid()}")
'''
PID_TEST = '''
import asyncio
from skills.own_pid.skill import Skill


def test_pid():
    assert asyncio.run(Skill().execute(text="pid")).output.startswith("pid ")
'''


class Sleeper(BaseTool):
    """Writes its pid and the pid of a Python it started, then sleeps past any test timeout."""

    name: ClassVar[str] = "sleeper"
    description: ClassVar[str] = "sleeps"
    parameters: ClassVar[dict] = {"type": "object", "properties": {"pids": {"type": "string"}, "s": {"type": "number"}}, "required": ["pids", "s"]}

    async def execute(self, pids: str, s: float) -> ToolResult:
        import subprocess

        child = subprocess.Popen([sys.executable, "-c", f"import time; time.sleep({s})"])
        Path(pids).write_text(f"{os.getpid()} {child.pid}", encoding="utf-8")
        time.sleep(s)
        return ToolResult(output="woke")


class Exiter(Sleeper):
    async def execute(self, pids: str, s: float) -> ToolResult:
        sys.exit(3)


def gone(pid: int, within: float = 5.0) -> bool:
    end = time.monotonic() + within
    while time.monotonic() < end:
        try:
            if not psutil.Process(pid).is_running() or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return True
        except psutil.NoSuchProcess:
            return True
        time.sleep(0.1)
    return False


def protected(kind: str) -> Path:
    paths = guard.protected_paths()
    if kind == "journal":
        return Path(paths[0])
    if kind == "keys":
        return Path([p for p in paths if p.endswith("brains.json")][0])
    return Path([p for p in paths if p.endswith(os.sep)][0].rstrip("\\/")) / "snapshot.json"


@pytest.mark.parametrize("kind", ["journal", "keys", "backup"])
def test_a_skill_cannot_write_the_journal_keys_or_backups(tmp_path, kind):
    target = protected(kind)
    assert str(target).startswith(str(tmp_path))  # conftest's journal: nothing real is at stake
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("before", encoding="utf-8")
    j, f, coll = factory(tmp_path)
    row = asyncio.run(f.create("note_writer", "write a note into a file", WRITER, WRITER_TEST))
    assert row["status"] == "VERIFIED", row["evidence"]
    with pytest.raises(PermissionError, match="running core|backups are SYRAX's evidence"):
        asyncio.run(coll.execute(name="note_writer", tool_input={"path": str(target), "text": "after"}))
    assert target.read_text(encoding="utf-8") == "before"
    ok = tmp_path / "work" / "note.txt"
    ok.parent.mkdir()
    out = asyncio.run(coll.execute(name="note_writer", tool_input={"path": str(ok), "text": "fine"}))
    assert out.output == "wrote 4 chars" and ok.read_text(encoding="utf-8") == "fine"  # an ordinary file is written


def test_a_python_the_skill_starts_is_guarded_too(tmp_path):
    journal = protected("journal")
    journal.write_text("before", encoding="utf-8")
    j, f, coll = factory(tmp_path)
    row = asyncio.run(f.create("py_runner", "run a line of python in a fresh interpreter", SPAWNER, SPAWNER_TEST))
    assert row["status"] == "VERIFIED", row["evidence"]
    out = asyncio.run(coll.execute(name="py_runner", tool_input={"line": f"open(r'{journal}', 'w').write('after')"}))
    assert out.output == "exit 1" and "written only by the running core" in out.error
    assert journal.read_text(encoding="utf-8") == "before"


def test_a_call_past_its_timeout_is_killed_with_what_it_started(tmp_path, monkeypatch):
    monkeypatch.setattr(skills, "SKILL_CALL_TIMEOUT_S", 6.0)
    pids = tmp_path / "pids.txt"
    out = asyncio.run(skills.IsolatedSkill.wrap(Sleeper()).execute(pids=str(pids), s=25))
    assert out.error.startswith("`sleeper` did not finish within 6 s, so SYRAX stopped it")
    worker, grandchild = (int(x) for x in pids.read_text(encoding="utf-8").split())
    assert worker != os.getpid()  # the skill ran in a process of its own
    assert gone(worker) and gone(grandchild)  # nothing keeps running in the background


def test_a_normal_skill_answers_from_its_own_process(tmp_path):
    j, f, coll = factory(tmp_path)
    assert asyncio.run(f.create("word_count", "count words", GOOD, GOOD_TEST))["status"] == "VERIFIED"
    assert asyncio.run(coll.execute(name="word_count", tool_input={"text": "a b c d"})).output == "4"
    assert asyncio.run(f.create("own_pid", "say which process runs a skill", PID, PID_TEST))["status"] == "VERIFIED"
    out = asyncio.run(coll.execute(name="own_pid", tool_input={"text": "pid"}))
    assert isinstance(out, ToolResult) and out.output.startswith("pid ")
    assert int(out.output.split()[1]) != os.getpid()


def test_a_skill_that_exits_does_not_exit_the_server(tmp_path):
    with pytest.raises(RuntimeError, match="SystemExit"):
        asyncio.run(skills.IsolatedSkill.wrap(Exiter()).execute(pids=str(tmp_path / "p"), s=0))
