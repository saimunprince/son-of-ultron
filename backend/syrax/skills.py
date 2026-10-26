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

import ast
import asyncio
import hashlib
import importlib.util
import inspect
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
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

# Live 2026-10-01: asked to "make yourself better", SYRAX wrote a skill that
# terminated every process above 20 % memory, and its test ran it for real on
# the owner's machine. A skill's tests execute its code on the host, so code
# that can hurt the machine is refused before anything runs. A human who wants
# such a capability writes it by hand.
from syrax import guard, permissions  # noqa: E402
from syrax.guard import HOST_HARM, TREE_DELETE, WEAKENS_GUARD  # noqa: E402  (one list for skills, python_execute and permissions)

# Live 2026-10-25 (audit): a skill runs in the server process, so code that assigns to, patches or reloads the
# gate's own modules (guard.WEAKENS_GUARD) never runs here, not even its tests.
UNSAFE = HOST_HARM + (TREE_DELETE,) + WEAKENS_GUARD

# Skill lifecycle (audit 2026-10-25): `version` in the registry counts verifications; `code_version` follows the
# content hash and moves only when the code does. Before new files go over a VERIFIED skill its files are kept under
# .versions/<code_version>/ (the last KEPT_VERSIONS), so the human can roll back; DISABLED sticks until the human
# enables; a new name that duplicates a VERIFIED skill's purpose (or its arguments and much of its purpose) is refused.
VERSIONS_DIR = ".versions"
KEPT_VERSIONS = 5
DUPLICATE_OVERLAP = 0.7  # purposes this alike are the same skill, whatever the arguments
SAME_ARGS_MIN = 2  # identical argument names count only from this many (translate {text} may live beside word_count {text})
SAME_ARGS_OVERLAP = 0.4  # ... and only with this much of the purpose in common


def hash_sources(sources: Dict[str, str]) -> str:
    """sha256 over {file name: text}, sorted by name, newlines normalized (CRLF on disk never changes the hash)."""
    h = hashlib.sha256()
    for fname in sorted(sources):
        text = (sources[fname] or "").replace("\r\n", "\n").replace("\r", "\n")
        h.update(fname.encode("utf-8") + b"\0" + text.encode("utf-8") + b"\0")
    return h.hexdigest()


def content_hash(skill_dir: Path) -> Optional[str]:
    """The hash of a skill folder's own .py files; None when there are none. Kept versions (.versions/) are not part of it."""
    files = sorted(p for p in Path(skill_dir).glob("*.py") if p.is_file())
    if not files:
        return None
    return hash_sources({p.name: p.read_text(encoding="utf-8", errors="replace") for p in files})


def schema_properties(code: str) -> Optional[set]:
    """The property names of `parameters` in `class Skill`, read from the source without running it (the code is not
    trusted before its safety check). None when the class, the dict or its literal keys cannot be found."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return None
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == "Skill"):
            continue
        for stmt in node.body:
            target = stmt.target if isinstance(stmt, ast.AnnAssign) else (stmt.targets[0] if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 else None)
            if not (isinstance(target, ast.Name) and target.id == "parameters" and isinstance(getattr(stmt, "value", None), ast.Dict)):
                continue
            for k, v in zip(stmt.value.keys, stmt.value.values):
                if isinstance(k, ast.Constant) and k.value == "properties" and isinstance(v, ast.Dict):
                    return {pk.value for pk in v.keys if isinstance(pk, ast.Constant) and isinstance(pk.value, str)}
            return set()
    return None


def purpose_overlap(a: str, b: str) -> float:
    """Jaccard overlap of two purposes' content words (memory.content_words: words of 3+ letters minus stop words)."""
    from syrax.memory import content_words

    wa, wb = content_words(a or ""), content_words(b or "")
    return len(wa & wb) / max(1, len(wa | wb))


def unsafe_reasons(*sources: str) -> List[str]:
    text = "\n".join(sources)
    out: List[str] = []
    for rx, why in UNSAFE:
        if why not in out and rx.search(text):
            out.append(why)
    return out


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
    # Live 2026-10-25 (audit): this child inherited a plain os.environ, so a skill's test could write brains.json
    # or the journal that python_execute's children are kept away from. It gets the same guard now, as an env of
    # its own (guard.child_env would set it on the server's os.environ): SYRAX_GUARD_PATHS, and the sitecustomize
    # that installs the guard first on PYTHONPATH.
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([guard.SITE_DIR, str(skill_dir.parent.parent), str(BACKEND_ROOT)]),
        guard.ENV: os.pathsep.join(guard.protected_paths()),
        "SYRAX_JOURNAL_FILE": str(skill_dir / ".test-journal.db"),
        "OPENMANUS_DISABLE_BROWSER_USE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    _clean_bytecode(skill_dir)  # py_compile above wrote a .pyc
    try:
        proc = subprocess.run(
            # --rootdir: pytest lists every folder between its rootdir and the test; under %TEMP% that
            # once tripped over a Chrome temp folder vanishing mid-listing (2026-10-12) and failed good skills
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", str(skill_dir), str(skill_dir / "test_skill.py")],
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


# A registered skill runs in a worker thread with its own event loop. SYRAX writes its
# skills, and one blocking call froze the whole server live on 2026-10-12: disk_usage ran
# os.walk("C:\\") inside its async execute(), and WebSocket, voice and /health all stopped
# (stall-20261012-163219.txt). Now a skill can block only its own thread, and after
# SKILL_CALL_TIMEOUT_S the agent gets an error back while the thread finishes on its own.
SKILL_CALL_TIMEOUT_S = 180.0
_SKILL_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="syrax-skill")


def _run_in_own_loop(tool: BaseTool, kwargs: dict) -> Any:
    return asyncio.run(tool.execute(**kwargs))


class IsolatedSkill(BaseTool):
    """The live tool for a skill: same name, description and schema, executed off the server's loop."""

    inner: Any = Field(default=None, exclude=True)

    @classmethod
    def wrap(cls, tool: BaseTool) -> "IsolatedSkill":
        return cls(name=tool.name, description=tool.description, parameters=tool.parameters, inner=tool)

    @property
    def risk(self) -> str:
        return str(getattr(self.inner, "risk", "") or "")

    async def execute(self, **kwargs) -> Any:
        job = asyncio.get_running_loop().run_in_executor(_SKILL_POOL, _run_in_own_loop, self.inner, kwargs)
        try:
            return await asyncio.wait_for(asyncio.shield(job), SKILL_CALL_TIMEOUT_S)
        except asyncio.TimeoutError:
            return ToolResult(error=f"`{self.name}` did not finish within {int(SKILL_CALL_TIMEOUT_S)} s, so SYRAX stopped waiting "
                                    "(the call keeps running in the background and its result is dropped). Try a smaller input.")


def schema_problems(tool: BaseTool) -> List[str]:
    """Arguments of execute() that its JSON schema does not declare. A model only
    knows the arguments the schema shows (live 2026-10-12: SYRAX built disk_usage
    with execute(path, top_n) and no `parameters`; its own tests passed, and no
    model could have called it)."""
    params = getattr(tool, "parameters", None)
    params = params if isinstance(params, dict) else {}
    props = set((params.get("properties") or {}).keys()) if isinstance(params.get("properties"), dict) else set()
    required = set(params.get("required") or [])
    out = []
    for name, p in inspect.signature(tool.execute).parameters.items():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        if name not in props:
            out.append(f"execute() takes `{name}` but `parameters.properties` does not declare it")
        elif p.default is p.empty and name not in required:
            out.append(f"`{name}` has no default but is not in `parameters.required`")
    return out


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
            if not row.get("content_hash"):
                # Verified before skills carried a hash (the lifecycle, 2026-10-25) and never re-verified since (a
                # prebuilt skill stays CURRENT): live 2026-10-26, 17 of 17 rows had none. Without one, the first code
                # change kept code_version 1 and a second one overwrote .versions/1, the original code. The files on
                # disk are the verified ones: their hash is stored, no version moves.
                try:
                    self.journal.backfill_skill_hash_sync(row["name"], content_hash(self.root / row["name"]))
                except Exception:
                    pass  # the next verification stores it; a missing hash never stops a skill from loading
            try:
                src = self.root / row["name"] / "skill.py"
                unsafe = unsafe_reasons(src.read_text(encoding="utf-8", errors="replace")) if src.is_file() else []
                if unsafe:
                    raise ValueError("unsafe code: " + "; ".join(unsafe))
                self._register(row["name"])
                n += 1
            except Exception as e:  # a skill that no longer loads is not VERIFIED
                self.journal.set_skill_status_sync(row["name"], "FAILED", note=f"failed to load at boot: {e}")
        return n

    def _register(self, name: str) -> BaseTool:
        assert self.collection is not None
        tool = load_skill(self.root / name)
        problems = schema_problems(tool)
        if problems:
            raise ValueError("a model could not call it: " + "; ".join(problems))
        self._unregister(name)
        live = IsolatedSkill.wrap(tool)
        self.collection.add_tool(live)
        self.loaded[name] = live
        permissions.declare(name, self.risk_of(name, tool))
        return live

    def risk_of(self, name: str, tool: Optional[BaseTool] = None) -> str:
        """A skill's permission level: what its source shows, raised (never
        lowered) by a `risk` it declares on its Skill class; floor WRITE."""
        src = self.root / name / "skill.py"
        shown = permissions.level_of_source(src.read_text(encoding="utf-8", errors="replace"))[0] if src.is_file() else permissions.WRITE
        declared = str(getattr(tool, "risk", "") or "").upper()
        return permissions.highest(permissions.WRITE, shown, declared if declared in permissions.ORDER else permissions.WRITE)

    def _unregister(self, name: str) -> bool:
        permissions.undeclare(name)
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

    # ——— lifecycle: kept versions, disable, duplicates ———

    def versions_dir(self, name: str) -> Path:
        return self.root / name / VERSIONS_DIR

    def kept_versions(self, name: str) -> List[int]:
        """The code versions kept on disk for `name`, oldest first."""
        d = self.versions_dir(name)
        if not d.is_dir():
            return []
        return sorted(int(p.name) for p in d.iterdir() if p.is_dir() and p.name.isdigit())

    def keep_version(self, name: str, new_hash: Optional[str] = None) -> Optional[int]:
        """Copy a VERIFIED skill's current files to .versions/<code_version>/ before new ones go over them, and
        prune to the last KEPT_VERSIONS. Nothing is kept when the skill is not VERIFIED, when there are no files,
        or when `new_hash` says the incoming code is the same. Returns the kept code version."""
        row = self.journal.skill(name)
        skill_dir = self.root / name
        if row is None or row.get("status") != "VERIFIED":
            return None
        current = content_hash(skill_dir)
        if current is None or (new_hash is not None and new_hash == current):
            return None
        code_version = int(row.get("code_version") or 1)
        dst = self.versions_dir(name) / str(code_version)
        shutil.rmtree(dst, ignore_errors=True)
        dst.mkdir(parents=True, exist_ok=True)
        for p in sorted(skill_dir.glob("*.py")) + [skill_dir / "skill.json"]:
            if p.is_file():
                shutil.copyfile(p, dst / p.name)
        for old in self.kept_versions(name)[:-KEPT_VERSIONS]:
            shutil.rmtree(self.versions_dir(name) / str(old), ignore_errors=True)
        return code_version

    async def rollback(self, name: str) -> dict:
        """The human's undo (WS `skill_rollback`; there is no agent tool for it): the newest kept version goes back
        into place and through the normal verify path, so it is registered only when its tests pass and ends FAILED
        with the evidence otherwise. The code it replaces is kept too (when VERIFIED), so a rollback can be undone
        by another. Refuses when nothing is kept. Journals skill.rolled_back {skill, from_hash, to_hash, status}."""
        row = self.journal.skill(name)
        if row is None:
            raise ValueError(f"no skill named {name!r}")
        kept = self.kept_versions(name)
        if not kept:
            raise ValueError(f"nothing kept for {name!r}: no earlier version to roll back to")
        src = self.versions_dir(name) / str(kept[-1])
        skill_dir = self.root / name
        from_hash = content_hash(skill_dir) or row.get("content_hash")
        to_hash = content_hash(src)
        self.keep_version(name, new_hash=to_hash)
        self._unregister(name)
        for p in sorted(src.glob("*.py")):
            shutil.copyfile(p, skill_dir / p.name)
        shutil.rmtree(src, ignore_errors=True)  # it is the live code now; keep_version stores it again when it is replaced
        _clean_bytecode(skill_dir)
        result = await self.verify(name)
        await self.journal.record("skill.rolled_back", {
            "skill": name, "from_hash": from_hash, "to_hash": to_hash, "status": result["status"],
            "from_code_version": row.get("code_version"), "code_version": result.get("code_version"), "kept_version": kept[-1],
        }, task_id=self.task_id_provider())
        return result

    def disabled_reason(self, name: str) -> Optional[str]:
        """Why skill_create/skill_test refuse `name`: the human disabled it (skill_test remove → DISABLED sticks in the
        registry) and only the human's `skill_enable` turns it back on. None when the name is free to use."""
        row = self.journal.skill(name)
        if row is not None and row.get("status") == "DISABLED":
            return f"{name} was disabled by the human; `skill_enable` turns it back on"
        return None

    async def enable(self, name: str) -> dict:
        """The human turns a DISABLED skill back on (WS `skill_enable`; no agent tool): it goes through the normal
        verify path and is registered again only when its tests pass. Journals skill.enabled {skill, status}."""
        row = self.journal.skill(name)
        if row is None:
            raise ValueError(f"no skill named {name!r}")
        if row.get("status") != "DISABLED":
            raise ValueError(f"{name!r} is not disabled (it is {row.get('status')})")
        result = await self.verify(name)
        await self.journal.record("skill.enabled", {"skill": name, "status": result["status"], "code_version": result.get("code_version"),
                                                    "content_hash": result.get("content_hash")}, task_id=self.task_id_provider())
        return result

    def duplicate_of(self, name: str, purpose: str, code: str) -> Optional[dict]:
        """The VERIFIED skill (another name) that `code`/`purpose` would duplicate: purposes whose content words
        overlap by DUPLICATE_OVERLAP or more, or the same set of SAME_ARGS_MIN+ `parameters` property names with
        SAME_ARGS_OVERLAP of the purpose in common. Identical argument names alone never refuse: `text` is what
        most text tools take."""
        props = schema_properties(code) or set()
        for row in self.journal.skills(status="VERIFIED"):
            if row["name"] == name:
                continue
            overlap = purpose_overlap(purpose, row.get("purpose") or "")
            if overlap >= DUPLICATE_OVERLAP:
                return row
            if len(props) >= SAME_ARGS_MIN and overlap >= SAME_ARGS_OVERLAP:
                src = self.root / row["name"] / "skill.py"
                theirs = schema_properties(src.read_text(encoding="utf-8", errors="replace")) if src.is_file() else None
                if theirs == props:
                    return row
        return None

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
        if self.journal.skill(name) is None:  # a new name; the same name is how a skill is improved
            twin = self.duplicate_of(name, purpose, code)
            if twin is not None:
                raise ValueError(f"a skill for this exists: {twin['name']} — {twin.get('purpose') or ''}; "
                                 f"extend it (skill_create with that name) instead of a duplicate")
        skill_dir = self.root / name
        task_id = self.task_id_provider()
        self.keep_version(name, new_hash=hash_sources({"skill.py": code, "test_skill.py": test_code, "__init__.py": ""}))
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
        sources = [(skill_dir / f).read_text(encoding="utf-8", errors="replace") for f in ("skill.py", "test_skill.py") if (skill_dir / f).is_file()]
        unsafe = unsafe_reasons(*sources)
        if unsafe:  # never run it, not even its tests
            result = {"status": "FAILED", "passed": 0, "failed": 0, "stage": "safety",
                      "evidence": "refused before running: the code " + "; ".join(unsafe)
                                  + ". Skills must not harm the host; a human adds such capabilities by hand."}
        else:
            result = await asyncio.to_thread(run_skill_tests, skill_dir)
        status = result["status"]
        result = {**result, "risk": self.risk_of(name, None)}  # what the skill's source may do (permissions.py)
        if status == "VERIFIED":
            try:
                await asyncio.to_thread(self._register, name)
                result["risk"] = permissions.level_of_tool(name)  # with the class's own declaration, if any
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
            content_hash=content_hash(skill_dir),  # code_version moves only when this does (journal.upsert_skill_sync)
        )
        _atomic_write(skill_dir / "skill.json", json.dumps(row, indent=2, default=str))
        return row

    async def remove(self, name: str) -> dict:
        if self.journal.skill(name) is None:
            raise ValueError(f"no skill named {name!r}")
        self._unregister(name)
        return await self.journal.run(self.journal.set_skill_status_sync, name, "DISABLED", "removed by request", self.task_id_provider())

    def list(self) -> List[dict]:
        from syrax import skillevo

        return skillevo.annotate([{**r, "registered": r["name"] in self.loaded, "kept_versions": self.kept_versions(r["name"])}
                                  for r in self.journal.skills()], self.journal)


# ——— tools ———


def _code_tag(row: dict) -> str:
    """`code v2 3fa9c0d1`: the code version and the short content hash (empty for a row that has neither)."""
    cv, h = row.get("code_version"), row.get("content_hash")
    return f"code v{cv} {str(h)[:8]}" if cv and h else (f"code v{cv}" if cv else "")


def _report(row: dict) -> str:
    ev = row.get("evidence") or {}
    head = (f"skill `{row['name']}` v{row['version']}: {row['status']} ({row['tests_passed']} passed, {row['tests_failed']} failed"
            + (f"; {_code_tag(row)}" if _code_tag(row) else "") + ")")
    if row["status"] == "VERIFIED":
        return head + ". It is registered now; call it by name like any other tool."
    return head + f"\nstage: {ev.get('stage')}\n{ev.get('evidence', '')}\nNot registered. Fix the code or the tests and create it again with the same name."


class SkillCreateTool(BaseTool):
    name: str = "skill_create"
    description: str = (
        "Build a new reusable tool for yourself. Provide Python code defining `class Skill(BaseTool)` "
        "(from app.tool.base import BaseTool, ToolResult) with `name` equal to the skill name, a "
        "`description`, JSON-schema `parameters`, and `async def execute(self, **kwargs) -> ToolResult`; "
        "every argument of execute() must be declared in `parameters` (properties, and `required` when it has no default) "
        "or the skill is not registered; "
        "optionally `risk: str` (READ_ONLY, WRITE, EXTERNAL_READ, SYSTEM, EXTERNAL_WRITE, DESTRUCTIVE) stating honestly what it may do, "
        "which can only raise the level its source already shows; "
        "plus pytest tests (test_code) that import it via "
        "`from skills.<name>.skill import Skill`. The skill is registered ONLY if the tests pass; "
        "otherwise you get the failure output. Re-running with the same name replaces the skill (the verified version "
        "it replaces is kept for the human's rollback). A new name whose purpose matches an existing skill (or shares its "
        "arguments and much of its purpose) is refused: extend that skill under its own name. A name the human disabled "
        "stays refused until they enable it."
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
        disabled = self.factory.disabled_reason(name)
        if disabled:
            return ToolResult(error=f"skill_create refused: {disabled}")
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
            f"[{r['tests_passed']} passed/{r['tests_failed']} failed]" + (f" {_code_tag(r)}" if _code_tag(r) else "")
            + (f" ({len(r['kept_versions'])} kept)" if r.get("kept_versions") else "") for r in rows
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
            disabled = self.factory.disabled_reason(name)
            if disabled:
                return ToolResult(error=disabled)
            row = await self.factory.verify(name)
        except (ValueError, JournalError) as e:
            return ToolResult(error=str(e))
        return ToolResult(output=_report(row))
