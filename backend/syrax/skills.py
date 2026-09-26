"""SYRAX skill factory: SYRAX writes a tool, its tests decide whether it exists.

    skill_create {name, purpose, code, test_code}
      → files written atomically under backend/skills/<name>/
      → py_compile both files
      → pytest test_skill.py in a subprocess (timeout)
      → registry row in the journal: VERIFIED (registered as a live tool)
        or FAILED (kept on disk with the pytest evidence, never registered)
      → skill.json metadata beside the code

A skill is a normal OpenManus tool: ``class Skill(BaseTool)`` with name,
description, parameters and ``async def execute(...)``. Once registered it
appears in the model's tool list on the next think step (ToolCallAgent calls
``available_tools.to_params()`` every step), so SYRAX can build a tool and use
it in the same task. VERIFIED skills are re-registered at boot from the
registry. Nothing here marks a skill VERIFIED without a passing test run.

Skill code runs in the server process, like every other tool. This is the
owner's own machine and the model already runs arbitrary code through
python_execute; the factory adds tests and a registry, not a sandbox.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import py_compile
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import Field

from app.tool.base import BaseTool, ToolResult
from app.tool.tool_collection import ToolCollection

from syrax.journal import BACKEND_ROOT, Journal, JournalError

SKILLS_ROOT = Path(os.getenv("SYRAX_SKILLS_DIR", str(BACKEND_ROOT / "skills")))
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,30}$")
TEST_TIMEOUT_S = 120.0
MAX_CODE_CHARS = 60_000


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _clean_bytecode(skill_dir: Path) -> None:
    """Drop cached bytecode. A rewrite of the same size within the same second
    would otherwise be served from the stale .pyc (pyc validation is mtime+size)."""
    import shutil

    shutil.rmtree(skill_dir / "__pycache__", ignore_errors=True)
    for pyc in skill_dir.glob("*.pyc"):
        try:
            pyc.unlink()
        except OSError:
            pass


def _summary(out: str) -> Tuple[int, int]:
    """(passed, failed) from a pytest summary line; (0, 0) when absent."""
    passed = failed = 0
    m = re.search(r"(\d+) passed", out)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+) failed", out)
    if m:
        failed = int(m.group(1))
    m = re.search(r"(\d+) error", out)
    if m:
        failed += int(m.group(1))
    return passed, failed


def run_skill_tests(skill_dir: Path, timeout: float = TEST_TIMEOUT_S) -> dict:
    """Compile and test a skill in a subprocess. Returns evidence, never raises.

    The tests import the skill as ``<root dir name>.<name>.skill`` (``skills.<name>.skill``
    for the default root), so the root's parent goes first on PYTHONPATH."""
    started = time.monotonic()
    skill_dir = Path(skill_dir)
    _clean_bytecode(skill_dir)
    for f in ("skill.py", "test_skill.py"):
        try:
            py_compile.compile(str(skill_dir / f), doraise=True)
        except py_compile.PyCompileError as e:
            return {"status": "FAILED", "stage": "compile", "file": f, "evidence": str(e)[-1500:], "passed": 0, "failed": 0, "ms": 0}
        except FileNotFoundError:
            return {"status": "FAILED", "stage": "compile", "file": f, "evidence": f"{f} missing", "passed": 0, "failed": 0, "ms": 0}
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(skill_dir.parent.parent), str(BACKEND_ROOT)]),
        "SYRAX_JOURNAL_FILE": str(skill_dir / ".test-journal.db"),
        "OPENMANUS_DISABLE_BROWSER_USE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    _clean_bytecode(skill_dir)  # py_compile above wrote a .pyc
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(skill_dir / "test_skill.py")],
            cwd=str(BACKEND_ROOT), capture_output=True, text=True, timeout=timeout, env=env,
        )
    except subprocess.TimeoutExpired:
        return {"status": "FAILED", "stage": "test", "evidence": f"tests timed out after {timeout}s", "passed": 0, "failed": 0, "ms": int((time.monotonic() - started) * 1000)}
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    passed, failed = _summary(out)
    ok = proc.returncode == 0 and passed > 0 and failed == 0
    tail = "\n".join(out.strip().splitlines()[-40:])
    return {
        "status": "VERIFIED" if ok else "FAILED",
        "stage": "test",
        "exit_code": proc.returncode,
        "evidence": tail if not ok else f"{passed} passed",
        "passed": passed,
        "failed": failed,
        "ms": int((time.monotonic() - started) * 1000),
    }


def load_skill(skill_dir: Path) -> BaseTool:
    """Import skills/<name>/skill.py and instantiate its Skill class."""
    path = skill_dir / "skill.py"
    _clean_bytecode(skill_dir)
    modname = f"syrax_skill_{skill_dir.name}_{int(path.stat().st_mtime_ns)}"
    spec = importlib.util.spec_from_file_location(modname, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[modname] = module
    spec.loader.exec_module(module)
    cls = getattr(module, "Skill", None)
    if cls is None or not (isinstance(cls, type) and issubclass(cls, BaseTool)):
        raise ImportError("skill.py must define class Skill(BaseTool)")
    tool = cls()
    if tool.name != skill_dir.name:
        raise ImportError(f"Skill.name must be {skill_dir.name!r}, got {tool.name!r}")
    return tool


class SkillFactory:
    def __init__(self, journal: Journal, root: Optional[Path] = None, task_id_provider: Optional[Callable[[], Optional[str]]] = None):
        self.journal = journal
        self.root = Path(root or SKILLS_ROOT)  # resolved at call time so tests can point it elsewhere
        self.task_id_provider = task_id_provider or (lambda: None)
        self.collection: Optional[ToolCollection] = None  # the live agent's tools
        self.loaded: Dict[str, BaseTool] = {}

    def attach(self, collection: ToolCollection) -> int:
        """Bind to the agent's tool collection and register VERIFIED skills."""
        self.collection = collection
        n = 0
        for row in self.journal.skills(status="VERIFIED"):
            try:
                self._register(row["name"])
                n += 1
            except Exception as e:  # a skill that no longer loads is not VERIFIED
                self.journal.set_skill_status_sync(row["name"], "FAILED", note=f"failed to load at boot: {e}")
        return n

    def _register(self, name: str) -> BaseTool:
        assert self.collection is not None
        tool = load_skill(self.root / name)
        self._unregister(name)
        self.collection.add_tool(tool)
        self.loaded[name] = tool
        return tool

    def _unregister(self, name: str) -> bool:
        if self.collection is None or name not in self.collection.tool_map:
            return False
        self.collection.tools = tuple(t for t in self.collection.tools if t.name != name)
        self.collection.tool_map.pop(name, None)
        self.loaded.pop(name, None)
        return True

    def reserved(self, name: str) -> bool:
        if self.collection is None:
            return False
        return name in self.collection.tool_map and name not in self.loaded

    async def create(self, name: str, purpose: str, code: str, test_code: str,
                     dependencies: Optional[List[str]] = None, known_limitations: Optional[List[str]] = None) -> dict:
        if not NAME_RE.match(name or ""):
            raise ValueError("name must match ^[a-z][a-z0-9_]{2,30}$")
        if self.reserved(name):
            raise ValueError(f"{name!r} is a built-in tool; pick another name")
        if not (purpose or "").strip():
            raise ValueError("purpose required")
        if not code or not test_code:
            raise ValueError("code and test_code are both required: a skill without tests cannot be verified")
        if len(code) > MAX_CODE_CHARS or len(test_code) > MAX_CODE_CHARS:
            raise ValueError("code too large")
        if "class Skill" not in code:
            raise ValueError("code must define class Skill(BaseTool)")
        if "def test_" not in test_code:
            raise ValueError("test_code must define at least one test_ function")
        skill_dir = self.root / name
        task_id = self.task_id_provider()
        _atomic_write(skill_dir / "skill.py", code)
        _atomic_write(skill_dir / "test_skill.py", test_code)
        _atomic_write(skill_dir / "__init__.py", "")
        await self.journal.record("skill.created", {"skill": name, "purpose": purpose[:160], "path": str(skill_dir)}, task_id=task_id)
        return await self.verify(name, purpose=purpose, dependencies=dependencies, known_limitations=known_limitations, created_task_id=task_id)

    async def verify(self, name: str, purpose: Optional[str] = None, dependencies: Optional[List[str]] = None,
                     known_limitations: Optional[List[str]] = None, created_task_id: Optional[str] = None) -> dict:
        skill_dir = self.root / name
        if not (skill_dir / "skill.py").is_file():
            raise ValueError(f"no skill named {name!r}")
        existing = self.journal.skill(name)
        purpose = purpose or (existing or {}).get("purpose") or name
        result = await asyncio.to_thread(run_skill_tests, skill_dir)
        status = result["status"]
        if status == "VERIFIED":
            try:
                await asyncio.to_thread(self._register, name)
            except Exception as e:
                status = "FAILED"
                result = {**result, "stage": "load", "evidence": f"tests passed but the skill failed to load: {e}"}
                self._unregister(name)
        else:
            self._unregister(name)
        row = await self.journal.run(
            self.journal.upsert_skill_sync, name, purpose, str(skill_dir), status,
            evidence=result, tests_passed=result.get("passed", 0), tests_failed=result.get("failed", 0),
            dependencies=dependencies or (existing or {}).get("dependencies") or [],
            known_limitations=known_limitations or (existing or {}).get("known_limitations") or [],
            created_task_id=created_task_id or (existing or {}).get("created_task_id"),
        )
        _atomic_write(skill_dir / "skill.json", json.dumps(row, indent=2, default=str))
        return row

    async def remove(self, name: str) -> dict:
        if self.journal.skill(name) is None:
            raise ValueError(f"no skill named {name!r}")
        self._unregister(name)
        return await self.journal.run(self.journal.set_skill_status_sync, name, "DISABLED", "removed by request", self.task_id_provider())

    def list(self) -> List[dict]:
        return [{**r, "registered": r["name"] in self.loaded} for r in self.journal.skills()]


# ——— tools ———


def _report(row: dict) -> str:
    ev = row.get("evidence") or {}
    head = f"skill `{row['name']}` v{row['version']}: {row['status']} ({row['tests_passed']} passed, {row['tests_failed']} failed)"
    if row["status"] == "VERIFIED":
        return head + ". It is registered now; call it by name like any other tool."
    return head + f"\nstage: {ev.get('stage')}\n{ev.get('evidence', '')}\nNot registered. Fix the code or the tests and create it again with the same name."


class SkillCreateTool(BaseTool):
    name: str = "skill_create"
    description: str = (
        "Build a new reusable tool for yourself. Provide Python code defining `class Skill(BaseTool)` "
        "(from app.tool.base import BaseTool, ToolResult) with `name` equal to the skill name, a "
        "`description`, JSON-schema `parameters`, and `async def execute(self, **kwargs) -> ToolResult`; "
        "plus pytest tests (test_code) that import it via "
        "`from skills.<name>.skill import Skill`. The skill is registered ONLY if the tests pass; "
        "otherwise you get the failure output. Re-running with the same name replaces the skill."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "snake_case, 3-31 chars, e.g. csv_summarize"},
            "purpose": {"type": "string", "description": "One sentence: what it does and when to use it."},
            "code": {"type": "string", "description": "Contents of skill.py"},
            "test_code": {"type": "string", "description": "Contents of test_skill.py (pytest)"},
            "dependencies": {"type": "array", "items": {"type": "string"}, "description": "Python packages or binaries it needs"},
            "known_limitations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["name", "purpose", "code", "test_code"],
    }
    factory: Optional[Any] = Field(default=None, exclude=True)

    async def execute(self, name: str, purpose: str, code: str, test_code: str,
                      dependencies: Optional[list] = None, known_limitations: Optional[list] = None) -> ToolResult:
        if self.factory is None:
            return ToolResult(error="skill factory unavailable")
        try:
            row = await self.factory.create(name, purpose, code, test_code, dependencies, known_limitations)
        except (ValueError, JournalError) as e:
            return ToolResult(error=f"skill_create refused: {e}")
        return ToolResult(output=_report(row))


class SkillListTool(BaseTool):
    name: str = "skill_list"
    description: str = "List the skills you have built: status, tests, version, purpose, whether registered."
    parameters: dict = {"type": "object", "properties": {}}
    factory: Optional[Any] = Field(default=None, exclude=True)

    async def execute(self) -> ToolResult:
        if self.factory is None:
            return ToolResult(error="skill factory unavailable")
        rows = self.factory.list()
        if not rows:
            return ToolResult(output="No skills built yet.")
        return ToolResult(output="\n".join(
            f"- {r['name']} v{r['version']} {r['status']}{' (registered)' if r['registered'] else ''}: {r['purpose']} "
            f"[{r['tests_passed']} passed/{r['tests_failed']} failed]" for r in rows
        ))


class SkillTestTool(BaseTool):
    name: str = "skill_test"
    description: str = "Re-run a skill's tests and update its status; or remove a skill with action=remove."
    parameters: dict = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "action": {"type": "string", "enum": ["test", "remove"], "description": "default test"},
        },
        "required": ["name"],
    }
    factory: Optional[Any] = Field(default=None, exclude=True)

    async def execute(self, name: str, action: str = "test") -> ToolResult:
        if self.factory is None:
            return ToolResult(error="skill factory unavailable")
        try:
            if action == "remove":
                row = await self.factory.remove(name)
                return ToolResult(output=f"skill `{name}` disabled and unregistered.")
            row = await self.factory.verify(name)
        except (ValueError, JournalError) as e:
            return ToolResult(error=str(e))
        return ToolResult(output=_report(row))
