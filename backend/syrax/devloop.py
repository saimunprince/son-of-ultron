"""SYRAX autonomous development loop: change → gate → commit, or rollback.

    (the model edits files with str_replace_editor / skill_create as usual)
    release {summary}
      → inspect: git status/diff; refuse an empty diff, files outside the
        self-modification scope, or anything secret-looking
      → snapshot: save the full diff + the list of new files as a rollback
        point; record code.changed
      → gate: verify.run_gates (the same gate a human release uses);
        record verification.completed
      → GREEN  → git add <changed files>, git commit (message carries the
                 verification id), record commit.created; push only when
                 SYRAX_AUTOPUSH=1 (default off: the human pushes)
      → BLOCKED → git checkout -- <files>, delete the new files, record
                 rollback.created with the failing gates' evidence; the
                 agent gets the evidence and must change approach

Every claim in the report comes from a command's exit code or from git.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from pydantic import Field

from app.logger import logger
from app.tool.base import BaseTool, ToolResult

from syrax.journal import BACKEND_ROOT, Journal, JournalError
from syrax.verify import Gate, Verification, default_gates, run_gates, scan_diff_text

REPO_ROOT = BACKEND_ROOT.parent
# What SYRAX may change on its own. Everything else needs a human commit.
SCOPE = ("backend/syrax/", "backend/skills/", "backend/requirements-syrax.txt", "frontend/components/", "frontend/lib/", "frontend/app/", "docs/", "README.md")
FORBIDDEN = (".env", "config/config.toml", "config/brains.json", "journal.db", ".git/", "node_modules/", ".venv/", ".next/")
SNAPSHOT_DIR = BACKEND_ROOT / "config" / "rollback"
WORKTREES_DIR = REPO_ROOT / ".syrax" / "worktrees"  # one per autonomous task (M1, isolated evolution)


def remove_worktree(worktree: Path, live_root: Path) -> None:
    """Remove a task worktree without following links. A frontend gate links
    the live node_modules into a worktree for its duration; if it crashed and
    left the link, deleting the tree through it would delete the shared
    modules. The link is unlinked first, never followed."""
    import shutil

    link = worktree / "frontend" / "node_modules"
    try:
        if link.is_symlink() or getattr(os.path, "isjunction", lambda p: False)(link):
            os.rmdir(link) if os.name == "nt" else os.unlink(link)
    except OSError:
        pass
    _git(["worktree", "remove", "--force", str(worktree)], live_root)
    if worktree.exists() and not worktree.is_symlink():
        shutil.rmtree(worktree, ignore_errors=True)
    _git(["worktree", "prune"], live_root)


def _git(args: Sequence[str], cwd: Path, timeout: float = 60) -> subprocess.CompletedProcess:
    """git with its output read as UTF-8. Live 2026-10-19: the daily ledger release failed with "unsupported operand
    type(s) for +: 'NoneType' and 'str'": on Windows text mode read the diff as cp1252, a UTF-8 byte (0x90) killed
    the reader thread, and stdout came back None."""
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout)


def changed_files(root: Path) -> Dict[str, str]:
    """{path: status} from git status --porcelain (M, A, D, ?? …)."""
    out = _git(["status", "--porcelain", "--untracked-files=all"], root)
    if out.returncode != 0:
        raise RuntimeError(f"git status failed: {out.stderr.strip()}")
    files: Dict[str, str] = {}
    for ln in out.stdout.splitlines():
        if len(ln) < 4:
            continue
        status, path = ln[:2].strip() or "M", ln[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        files[path] = status
    return files


_ASSERTING_CALLS = frozenset({"raises", "warns", "fail", "deprecated_call"})


def _test_functions(src: str) -> Optional[Dict[str, bool]]:
    """{test name: asserts something} for a test module; None when it does not parse. A test asserts when its
    body has an assert, a pytest.raises/warns/fail, a self.assert*, or a call to a helper that asserts (one
    defined in the module, or imported from another test module)."""
    import ast

    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None

    def asserts(fn: ast.AST, helpers: set) -> bool:
        for node in ast.walk(fn):
            if isinstance(node, ast.Assert):
                return True
            if isinstance(node, ast.Call):
                f = node.func
                name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
                if name in _ASSERTING_CALLS or name.startswith("assert") or name in helpers:
                    return True
        return False

    fns = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef) and n.name.startswith("Test")):
        fns += [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    helpers = {a.asname or a.name for n in tree.body if isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[-1].startswith(("test_", "conftest"))
               for a in n.names}
    helpers |= {n.name for n in fns if not n.name.startswith("test") and asserts(n, set())}
    return {n.name: asserts(n, helpers) for n in fns if n.name.startswith("test")}


def assertless_tests(root: Path, files: Dict[str, str]) -> List[str]:
    """New tests in the change that assert nothing (an existing test may not change at all: judge_problems).
    Live 2026-10-15 (objective 232, attempt 3): with its own new test failing, SYRAX replaced the asserts with
    `pass` "to allow the release"; a test that asserts nothing proves nothing, and the review reads only
    removed lines and is skipped when no other brain answers."""
    out = []
    for path in sorted(files):
        if not re.search(r"(^|/)test_[^/]*\.py$", path) or not (root / path).is_file():
            continue
        found = _test_functions((root / path).read_bytes().decode("utf-8", "replace")) or {}
        out += [f"{path}::{name} asserts nothing" for name, ok in found.items() if not ok]
    return out


# Tools that can write files anywhere in the repository (paths unknown), and
# the editor, whose edits are journaled path by path (code.changed).
WRITER_TOOLS = frozenset({"python_execute", "skill_create"})
EDITOR_TOOL = "str_replace_editor"
EDITOR_TOOLS = frozenset({EDITOR_TOOL, "apply_patch"})  # both journal exactly which files they touched (code.changed)


def owned_files(files: Dict[str, str], tools_used: Iterable[str], edited_paths: Iterable[str]) -> Dict[str, str]:
    """Which of the not-baseline changes a task is responsible for, judged from
    what it actually ran. A task that never ran a file-writing tool owns
    nothing (a human editing the tree while it ran is not its doing); a task
    that only used the editor owns exactly the paths it edited; a task that
    ran python or built a skill may have written anywhere, so it owns every
    change that was not there when it started."""
    used = set(tools_used)
    if not used & (WRITER_TOOLS | EDITOR_TOOLS):
        return {}
    if used & WRITER_TOOLS:
        return dict(files)
    edited = {p.replace("\\", "/") for p in edited_paths}
    return {p: st for p, st in files.items() if p.replace("\\", "/") in edited}


# The code that decides whether SYRAX succeeded. Live 2026-10-01: working its own
# objective "make quality case research_cite pass", SYRAX changed the case's
# check from `research` to `know` and called release ("fix the check to expect
# the tool that is actually invoked"). An agent that edits its judge can pass
# anything. Autonomous work fixes behaviour; a human changes the judge.
JUDGES = (
    "backend/syrax/quality.py", "backend/syrax/verify.py", "backend/syrax/bench.py",
    "backend/syrax/autonomy.py", "backend/syrax/experiments.py", "backend/syrax/versions.py",
    "backend/syrax/devloop.py", "backend/syrax/limits.py", "backend/syrax/plan.py", "backend/syrax/followup.py", "backend/syrax/skills.py", "backend/syrax/skillevo.py", "backend/syrax/consolidate.py", "backend/syrax/permissions.py",
    # and what guards the evidence: the journal's owner/read-only rules and the
    # python_execute guard (an agent must not take down its own guard rails)
    "backend/syrax/journal.py", "backend/syrax/guard.py", "backend/syrax/_guard_site/sitecustomize.py",
    "backend/syrax/tools.py", "backend/syrax/review.py",
    # and what measures it: a system that reports its own rise must not edit the ruler
    "backend/syrax/rise.py", "backend/syrax/capmatrix.py", "backend/syrax/contracts.py", "backend/syrax/ledger.py",
    "backend/syrax/repro.py",
    "backend/syrax/archive.py", "backend/syrax/auth.py",
    "backend/syrax/devlog.py",
    "backend/syrax/codebench.py", "backend/syrax/probe.py",
    # and what decides which features exist and which ones SYRAX may build on its own
    "backend/syrax/catalog.py", "backend/syrax/prebuilt.py",
    # and what shows the human what SYRAX is doing
    "backend/syrax/phases.py",
)


def judge_problems(files: Dict[str, str]) -> List[str]:
    """Changes SYRAX may not release in any task: the judges (the protected set,
    JUDGES above, which includes this definition), and any edit or deletion of an
    existing test (new tests are welcome). Owner rule, 2026-10-13: only a
    human-made commit changes the protected set; when the human asks SYRAX for such
    a change, the edit stays in the working tree for the human to commit."""
    problems = []
    for path, st in files.items():
        name = path.rsplit("/", 1)[-1]
        if path in JUDGES:
            problems.append(f"{path}: this file judges SYRAX's own work; only a human changes it")
        elif (name.startswith("test_") or name.endswith(".test.ts")) and st != "??":
            problems.append(f"{path}: existing tests are the contract; add a new test instead of changing this one")
    return problems


_PATH_TOKEN = re.compile(r"[\w./-]+\.\w+")
_REPO_TOPS = ("backend/", "docs/", "frontend/", "hud/")


def case_files(case_ids) -> Dict[str, List[str]]:
    """{repository path: [case ids]} for the files the prompts of these quality cases name."""
    from syrax import quality

    out: Dict[str, List[str]] = {}
    wanted = set(case_ids or [])
    for case in quality._cases(quality.WORKSPACE):
        if case["id"] not in wanted:
            continue
        for token in _PATH_TOKEN.findall(str(case.get("prompt") or "")):
            path = token[2:] if token[:2] in ("a/", "b/") else token  # a diff in the prompt names a/README.md
            if (path.startswith(_REPO_TOPS) or path == "README.md") and case["id"] not in out.get(path, []):
                out.setdefault(path, []).append(case["id"])
    return out


def fixture_problems(files: Dict[str, str], objective: Optional[dict]) -> List[str]:
    """Live 2026-10-14 (task ee5bb152e8fa): working on "make quality case self_patch_stale pass", SYRAX
    rewrote README's title so the case's stale patch would apply, and the gate passed it (it landed
    only because the branch had moved). A case measures SYRAX's behaviour; an objective born from a
    case may change SYRAX, never the files that case works on."""
    spec = (objective or {}).get("check_spec") or {}
    if spec.get("kind") not in ("quality_case_passes", "quality_recovered"):
        return []
    ev = (objective or {}).get("evidence") or {}
    ids = [spec.get("case")] if spec.get("case") else list(((ev.get("quality") or {}).get("failed")) or [])
    named = case_files(ids)
    return [f"{path}: named by quality case {', '.join(named[path])}; an objective to make a case pass changes SYRAX's "
            "behaviour, never the files the case works on" for path in files if path in named]


PLAN_FIELDS = ("why", "risk", "tests")


def impact_of(files: Dict[str, str], root: Path) -> Dict[str, Any]:
    """Which system-map components a change touches and the tests that cover
    them (Phase 4: know what depends on the module before changing it)."""
    try:
        smap = json.loads((root / "docs" / "system_map.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"components": [], "component_tests": []}
    touched, tests = [], []
    for c in smap.get("components", []):
        code = [str(x).split(" ")[0] for x in c.get("code") or []]
        if any(f in code for f in files):
            touched.append(c.get("component"))
            tests += [str(t).split(" ")[0] for t in c.get("tests") or []]
    return {"components": touched, "component_tests": sorted(set(tests))}


def scope_problems(files: Dict[str, str]) -> List[str]:
    problems = []
    for path in files:
        if any(f in path for f in FORBIDDEN):
            problems.append(f"{path}: forbidden (secrets, runtime state or vendored code)")
        elif not any(path.startswith(s) or path == s.rstrip("/") for s in SCOPE):
            problems.append(f"{path}: outside the self-modification scope {SCOPE}")
    return problems


class DevLoop:
    def __init__(self, journal: Journal, root: Path = REPO_ROOT, gates: Optional[Callable[[], List[Gate]]] = None,
                 task_id_provider: Optional[Callable[[], Optional[str]]] = None, snapshot_dir: Optional[Path] = None,
                 worktrees_dir: Optional[Path] = None):
        self.journal = journal
        self.root = Path(root)
        # M1: while a task is isolated, root is its worktree and live_root the running tree
        self.live_root = self.root
        self.isolated: Optional[Path] = None
        self.worktrees_dir = Path(worktrees_dir or (self.live_root / ".syrax" / "worktrees"))
        self.live_baseline: Dict[str, str] = {}
        # per task: what each failed gate run failed on (gate names, failing tests)
        self.failures: Dict[Optional[str], List[tuple]] = {}
        # async (info, summary, author_brains) -> {approve, reasons, reviewer} | {skipped};
        # set by the core: a different brain must approve an autonomous change
        self.reviewer: Optional[Callable[..., Any]] = None
        self.gates = gates or (lambda: default_gates(self.root))
        self.task_id_provider = task_id_provider or (lambda: None)
        self.snapshot_dir = Path(snapshot_dir or SNAPSHOT_DIR)
        self.autopush = os.getenv("SYRAX_AUTOPUSH", "0") == "1"
        # Files that were already modified before the current task started. A task
        # may only release, and may only roll back, what it changed itself; a
        # human's uncommitted work is never touched.
        self.baseline: Dict[str, str] = {}

    @staticmethod
    def failure_signature(report: Dict[str, Any]) -> tuple:
        """What a failed gate run failed on: the gates and the failing test ids."""
        failing = report.get("failing") or []
        text = " ".join(str(f.get("evidence") or "") for f in failing)
        return (tuple(sorted(f.get("name") or "" for f in failing)), tuple(sorted(set(re.findall(r"FAILED (\S+)", text)))))

    def begin_task(self) -> Dict[str, str]:
        """Record the pre-existing working-tree changes when a task starts."""
        try:
            self.baseline = changed_files(self.root)
        except Exception:
            self.baseline = {}
        return dict(self.baseline)

    # ——— M1: isolated evolution ———

    def isolate(self, task_id: str) -> Path:
        """Give the task its own worktree at HEAD: its edits, the gate and the
        commit happen there; the running tree changes only when a released
        commit is fast-forwarded into it. Leftover worktrees (one task runs at a
        time) are removed first."""
        from syrax.versions import prepare_worktree

        self.prune_worktrees()
        wt = self.worktrees_dir / str(task_id)
        wt.parent.mkdir(parents=True, exist_ok=True)
        add = _git(["worktree", "add", "--detach", str(wt), "HEAD"], self.live_root)
        if add.returncode != 0:
            raise RuntimeError(f"git worktree add failed: {(add.stderr or add.stdout).strip()[:300]}")
        prepare_worktree(wt, self.live_root)  # the untracked runtime files a checkout needs to import
        self.live_baseline = dict(self.baseline)  # the human's uncommitted work in the running tree stays protected
        self.isolated, self.root, self.baseline = wt, wt, {}
        return wt

    def discard(self) -> None:
        """Drop the task's worktree and point the loop at the running tree again."""
        wt = self.isolated
        if wt is None:
            return
        self.isolated, self.root, self.baseline = None, self.live_root, dict(self.live_baseline)
        remove_worktree(wt, self.live_root)

    def prune_worktrees(self) -> List[str]:
        """Remove task worktrees left behind (a crash, a restart). Not the current one."""
        removed = []
        if self.worktrees_dir.is_dir():
            for wt in sorted(self.worktrees_dir.iterdir()):
                if wt.is_dir() and wt != self.isolated:
                    remove_worktree(wt, self.live_root)
                    removed.append(wt.name)
        return removed

    def land(self, sha: str) -> Dict[str, Any]:
        """Fast-forward the running tree to a commit made in the task's worktree.
        Only a fast-forward: if the running tree's branch moved meanwhile, or a
        human's uncommitted change is in the way, nothing lands, with one
        exception: a commit that changes only docs/ files nobody else touched
        since its base is replayed onto the moved branch and lands then
        (live 2026-10-13: the daily ledger, docs only, lost its fast-forward to
        a human's code commit made while its gate ran, and was not published)."""
        out = _git(["merge", "--ff-only", sha], self.live_root)
        if out.returncode == 0:
            return {"ok": True, "output": (out.stdout + out.stderr).strip()[-500:]}
        replayed = self._replay_docs_only(sha)
        if replayed:
            again = _git(["merge", "--ff-only", replayed["sha"]], self.live_root)
            if again.returncode == 0:
                return {"ok": True, "sha": replayed["sha"], "rebased_onto": replayed["onto"],
                        "output": f"docs-only commit replayed onto {replayed['onto'][:12]}, files nobody else touched: "
                                  + ", ".join(replayed["files"])}
        return {"ok": False, "output": (out.stdout + out.stderr).strip()[-500:]}

    def _replay_docs_only(self, sha: str) -> Optional[Dict[str, Any]]:
        files = [f for f in _git(["diff", "--name-only", f"{sha}^", sha], self.live_root).stdout.split() if f]
        if not files or not all(f.startswith("docs/") for f in files):
            return None
        onto = _git(["rev-parse", "HEAD"], self.live_root).stdout.strip()
        base = _git(["merge-base", onto, sha], self.live_root).stdout.strip()
        if not onto or not base:
            return None
        moved = set(_git(["diff", "--name-only", base, onto], self.live_root).stdout.split())
        if moved & set(files):
            return None  # someone else changed the same document: a human decides
        where = self.isolated or self.root
        _git(["checkout", "-q", "--detach", onto], where)
        pick = _git(["-c", "user.name=SYRAX", "-c", "user.email=syrax@localhost", "cherry-pick", "--allow-empty", sha], where)
        if pick.returncode != 0:
            _git(["cherry-pick", "--abort"], where)
            return None
        return {"sha": _git(["rev-parse", "HEAD"], where).stdout.strip(), "onto": onto, "files": files}

    def task_files(self, files: Dict[str, str]) -> Dict[str, str]:
        """Changed files this task is responsible for: everything not dirty at task start."""
        return {p: st for p, st in files.items() if p not in self.baseline}

    # ——— steps ———

    def inspect(self) -> Dict[str, Any]:
        all_files = changed_files(self.root)
        files = self.task_files(all_files)
        if not files:
            if all_files:
                raise ValueError("nothing to release: the only changes in the tree predate this task (a human's uncommitted work: "
                                 + ", ".join(sorted(all_files)) + ")")
            raise ValueError("nothing to release: the working tree has no changes")
        problems = scope_problems(files)
        task_id = self.task_id_provider()
        task = self.journal.task(task_id) if task_id else None
        judged = judge_problems(files)  # every task kind: only a human-made commit changes the judges
        problems += judged
        active = None
        if task and task.get("kind") == "autonomous":
            oid = self._active_objective_id(task)
            active = self.journal.objective(oid) if oid is not None else None
            problems += fixture_problems(files, active)
        if not problems and active and ((active.get("check_spec") or {}).get("repro")
                                         or (active.get("check_spec") or {}).get("kind") == "repro_proven"):
            # a brief filed with a judge-proven test lands with exactly that test, still failing on this base
            from syrax import repro

            problems += repro.release_problems(self.root, self.live_root, files, active)
        if judged and task and task.get("kind") not in ("autonomous", "eval"):
            problems.append("the edit stays in the working tree: tell the human it is there for them to review and commit")
        if problems:
            raise ValueError("refused: " + "; ".join(problems))
        diff = _git(["diff", "HEAD", "--", *[p for p, st in files.items() if st != "??"]], self.root).stdout if any(st != "??" for st in files.values()) else ""
        untracked_text = ""
        for path, st in files.items():
            if st == "??":
                p = self.root / path
                try:
                    body = p.read_text(encoding="utf-8", errors="replace")
                except (OSError, UnicodeDecodeError):
                    continue
                untracked_text += f"+++ b/{path}\n" + "\n".join("+" + ln for ln in body.splitlines()) + "\n"
        findings = scan_diff_text(diff + untracked_text)
        if findings:
            raise ValueError("refused by diff scan: " + "; ".join(findings[:5]))
        broken = []
        for path in files:
            if path.endswith(".py") and (self.root / path).is_file():
                try:
                    compile((self.root / path).read_text(encoding="utf-8", errors="replace"), str(path), "exec")  # syntax only, no .pyc written
                except SyntaxError as e:
                    broken.append(f"{path}: line {e.lineno}: {e.msg}")
        if broken:
            raise ValueError("refused: python does not compile — fix it before the gate: " + "; ".join(broken))
        stat = _git(["diff", "HEAD", "--stat", "--", *files], self.root).stdout.strip()
        head = _git(["rev-parse", "HEAD"], self.root).stdout.strip()
        return {"files": files, "diff": diff, "untracked": [p for p, s in files.items() if s == "??"], "stat": stat, "head": head}

    def _preflight(self, files: Dict[str, str]) -> None:
        """Own work only: the tests that cover the change run before the full gate. Live 2026-10-15 (objective
        232, attempt 2): SYRAX released while its own new test failed; the gate took eight minutes to say so
        and the rollback took the edits away. Refused here, the edits stay for a fix forward."""
        from syrax import selfedit

        hollow = assertless_tests(self.root, files)
        if hollow:
            raise ValueError("refused: a test that asserts nothing proves nothing: " + "; ".join(hollow[:6]) + ". Your edits stay: "
                             "assert the behaviour the change is for; when the test fails, fix the code or the test's setup, "
                             "never the assertion away.")
        py = [p for p, st in files.items() if p.endswith(".py")]
        tests = selfedit.covering_tests(self.root, py) if py else []
        if not tests:
            return
        result = selfedit.run_tests(self.root, tests)
        if not result["ok"]:
            # Live 2026-10-15 (objective 249): an existing test pinned the old behaviour (`gpu is None`); SYRAX
            # edited it, was refused (existing tests are the contract), reverted, and ended without saying why.
            pinned = sorted({f"backend/{m}" for m in re.findall(r"FAILED (syrax/test_[\w/]+\.py)::", str(result.get("tail") or ""))} - set(files))
            contract = ("" if not pinned else
                        f"\nThe failing test is an existing one ({', '.join(pinned)}): it is the contract and you may not edit it. "
                        "If it pins the behaviour your objective asks to change, stop and say in your final answer which test "
                        "and assertion block the objective, so a human can update the contract.")
            raise ValueError("refused: the tests that cover your change fail, so the gate would roll it back; your edits "
                             f"stay, fix forward and release again. {result['summary']} ({', '.join(result['ran'])})\n"
                             + str(result.get("tail") or "")[-1500:] + contract)

    def snapshot(self, info: Dict[str, Any]) -> Path:
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        path = self.snapshot_dir / f"{int(time.time())}-{info['head'][:7]}.patch"
        body = info["diff"]
        for rel in info["untracked"]:
            try:
                body += f"\n# untracked: {rel}\n" + (self.root / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
        path.write_text(body, encoding="utf-8", newline="\n")  # a diff holding "\u2190" could not be written as cp1252 (2026-10-19)
        return path

    def rollback(self, info: Dict[str, Any]) -> Dict[str, Any]:
        tracked = [p for p, s in info["files"].items() if s != "??"]
        removed, restored = [], []
        if tracked:
            out = _git(["checkout", "--", *tracked], self.root)
            if out.returncode == 0:
                restored = tracked
        for rel in info["untracked"]:
            p = self.root / rel
            try:
                p.unlink()
                removed.append(rel)
            except OSError:
                pass
        clean = not changed_files(self.root)
        return {"restored": restored, "removed": removed, "clean": clean}

    def commit(self, info: Dict[str, Any], summary: str, verification_id: Optional[int]) -> Dict[str, Any]:
        files = list(info["files"])
        add = _git(["add", "--", *files], self.root)
        if add.returncode != 0:
            raise RuntimeError(f"git add failed: {add.stderr.strip()}")
        msg = f"syrax: {summary.strip()}\n\nVerified-By: syrax.verify #{verification_id}\nCo-Authored-By: SYRAX <syrax@localhost>\n"
        out = _git(["-c", "user.name=SYRAX", "-c", "user.email=syrax@localhost", "commit", "-q", "-m", msg], self.root)
        if out.returncode != 0:
            raise RuntimeError(f"git commit failed: {out.stderr.strip() or out.stdout.strip()}")
        head = _git(["rev-parse", "HEAD"], self.root).stdout.strip()
        if self.isolated is not None:  # the commit lives in the worktree until the running tree takes it
            landed = self.land(head)
            if not landed["ok"]:
                raise RuntimeError(f"committed {head[:12]} in the task's worktree but could not fast-forward the running tree "
                                   f"(it moved, or a human's change is in the way): {landed['output'][:300]}")
            if landed.get("sha"):
                return {"commit": landed["sha"], "files": files, "rebased_onto": landed["rebased_onto"]}
        return {"commit": head, "files": files}

    def push(self) -> Dict[str, Any]:
        branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], self.live_root).stdout.strip()
        out = _git(["push", "origin", branch], self.live_root, timeout=120)
        return {"ok": out.returncode == 0, "branch": branch, "output": (out.stdout + out.stderr).strip()[-500:]}

    # ——— the loop ———

    async def release(self, summary: str, plan: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Every attempt, whatever its outcome, leaves an experiment record:
        candidate = the change, baseline = HEAD, measured by the gate and the
        review; the verdict comes from the outcome, never from the summary."""
        try:
            report = await self._release(summary, plan)
        except (ValueError, JournalError) as e:
            # the commit the refused attempt started from: the archive's first publish (2026-10-15) showed
            # every refused row with no parent, so its lineage had holes
            head = (await asyncio.to_thread(_git, ["rev-parse", "HEAD"], self.root)).stdout.strip() or None
            await asyncio.to_thread(self.record_experiment, summary, plan, {"outcome": "REFUSED", "error": str(e), "head": head})
            raise
        await asyncio.to_thread(self.record_experiment, summary, plan, report)
        return report

    DECISION_VERDICT = {"COMMITTED": "CANDIDATE_BETTER", "ROLLED_BACK": "BASELINE_BETTER", "REVIEW_REJECTED": "BASELINE_BETTER",
                        "REFUSED": "BASELINE_BETTER", "COMMIT_FAILED": "INCONCLUSIVE"}

    def _active_objective_id(self, task: Optional[dict]) -> Optional[int]:
        """The objective an autonomous task works on: the cycle marks exactly one ACTIVE before it starts the task."""
        if not task or task.get("kind") != "autonomous":
            return None
        active = self.journal.objectives(limit=5, status="ACTIVE")
        return active[0]["id"] if len(active) == 1 else None

    def record_experiment(self, summary: str, plan: Optional[Dict[str, str]], report: Dict[str, Any]) -> Optional[dict]:
        """Write the attempt as an experiment. Never raises: a release must not fail on its own bookkeeping."""
        import hashlib
        import platform
        import sys

        try:
            task_id = self.task_id_provider()
            task = self.journal.task(task_id) if task_id else None
            decision = str(report.get("outcome") or "UNKNOWN")
            head = report.get("head") or _git(["rev-parse", "HEAD"], self.root).stdout.strip()
            diff = str(report.get("diff") or "")
            objective_id = self._active_objective_id(task)
            result = {
                "decision": decision,
                "objective_id": objective_id,
                "task_id": task_id,
                "task_kind": (task or {}).get("kind"),
                "source_revision": head,
                "environment": {"python": sys.version.split()[0], "platform": platform.platform()},
                "tests": {"verification_id": report.get("verification_id"), "status": report.get("verification"),
                          "gates": report.get("gates") or [], "failing": [f.get("name") for f in report.get("failing") or []]},
                "review": report.get("review"),
                "artifacts": {"files": sorted(report.get("files") or {}), "snapshot": report.get("snapshot"), "commit": report.get("commit"),
                              "diff_sha256": hashlib.sha256(diff.encode("utf-8", "replace")).hexdigest() if diff else None},
                "reason": report.get("error"),
                "plan": {k: v for k, v in (plan or {}).items() if v},
            }
            verdict = self.DECISION_VERDICT.get(decision, "INCONCLUSIVE")
            conclusion = {
                "COMMITTED": f"committed {str(report.get('commit') or '')[:12]} after gate #{report.get('verification_id')} GREEN",
                "ROLLED_BACK": f"rolled back: gate #{report.get('verification_id')} {report.get('verification')}",
                "REVIEW_REJECTED": "rolled back: a second brain rejected the change",
                "REFUSED": f"refused before the gate: {str(report.get('error') or '')[:200]}",
                "COMMIT_FAILED": f"gate GREEN but the commit failed: {str(report.get('error') or '')[:200]}",
            }.get(decision, decision)
            exp = self.journal.add_experiment_sync(
                f"release: {summary.strip()[:200]}", {"git_head": head}, {"files": result["artifacts"]["files"], "diff_sha256": result["artifacts"]["diff_sha256"]},
                "release_gate", result, conclusion, verdict, objective=str(objective_id) if objective_id is not None else None,
                next_action=None if decision == "COMMITTED" else "change the approach; the same change fails the same way",
                task_id=None,  # task-less on purpose: the task's own event sequence stays the release's
            )
            try:  # Phase 5: the attempt joins the archive of variants (parent → head, scored later by the quality suite)
                from syrax import archive

                archive.record_attempt(self.journal, report, summary, objective_id, task_id, (exp or {}).get("id"))
            except Exception as e:  # pragma: no cover
                logger.warning(f"could not archive the release attempt: {e}")
            return exp
        except Exception as e:  # pragma: no cover - bookkeeping must not break a release
            logger.warning(f"could not record the release experiment: {e}")
            return None

    async def _release(self, summary: str, plan: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        if not (summary or "").strip():
            raise ValueError("summary required")
        task_id = self.task_id_provider()
        task = self.journal.task(task_id) if task_id else None
        plan = {k: str(v).strip() for k, v in (plan or {}).items() if v and str(v).strip()}
        info = await asyncio.to_thread(self.inspect)  # scope and judge refusals come first
        if task and task.get("kind") == "autonomous":
            missing = [k for k in PLAN_FIELDS if not plan.get(k)]
            if missing:
                raise ValueError(
                    "an autonomous release needs a change plan; missing: " + ", ".join(missing)
                    + ". why = the evidence or objective it answers; risk = what could break; tests = which tests prove it"
                )
        seen = self.failures.get(task_id) or []
        if len(seen) >= 2 and seen[-1] == seen[-2] and any(seen[-1]):
            # Live 2026-10-11: one attempt re-released a README change five times, ~4 minutes of
            # gate each, every run failing the same 62 tests that had nothing to do with it.
            gates, tests = seen[-1]
            raise ValueError(
                f"refused: the gate failed twice in this task with the same failures ({', '.join(gates)}"
                + (f"; {len(tests)} failing tests, e.g. {tests[0]}" if tests else "") + "). They do not change with your "
                "edits, so a third run will fail the same way. Stop releasing and report what blocks you."
            )
        if task and task.get("kind") == "autonomous":
            await asyncio.to_thread(self._preflight, info["files"])
        impact = impact_of(info["files"], self.root)
        await self.journal.record("release.planned", {"summary": summary, "plan": plan, **impact}, task_id=task_id)
        snap = await asyncio.to_thread(self.snapshot, info)
        await self.journal.record(
            "code.changed", {"files": info["files"], "stat": info["stat"], "head": info["head"], "snapshot": str(snap)}, task_id=task_id,
        )
        cancel = threading.Event()
        try:
            verification: Verification = await asyncio.to_thread(run_gates, self.gates(), self.journal, task_id, cancel, info["head"])
        except asyncio.CancelledError:
            cancel.set()  # the task was stopped: its gate stops too, process tree and all
            raise
        vid = self.journal.verifications(limit=1)[0]["id"]
        report: Dict[str, Any] = {
            "summary": summary,
            "head": info["head"],
            "diff": info["diff"],
            "snapshot": str(snap),
            "files": info["files"],
            "verification_id": vid,
            "verification": verification.status,
            "gates": [{"name": g.name, "status": g.status, "required": g.required} for g in verification.gates],
            "failing": [{"name": g.name, "status": g.status, "evidence": g.evidence[-1500:]} for g in verification.gates if g.required and g.status != "PASS"],
        }
        if verification.status != "GREEN":
            self.failures.setdefault(task_id, []).append(self.failure_signature(report))
            rb = await asyncio.to_thread(self.rollback, info)
            await self.journal.record("rollback.created", {"reason": "verification BLOCKED", "verification_id": vid, **rb, "snapshot": str(snap)}, task_id=task_id)
            report.update({"outcome": "ROLLED_BACK", "rollback": rb, "snapshot": str(snap)})
            return report
        task = self.journal.task(task_id) if task_id else None
        if self.reviewer is not None and task and task.get("kind") in ("autonomous", "eval"):
            authors = sorted({e["payload"].get("provider") for e in self.journal.events(task_id) if e["type"] == "brain.answered"} - {None})
            told = summary + "".join(f"\n{k.capitalize()}: {v}" for k, v in plan.items())
            if impact["components"]:
                told += f"\nComponents touched: {', '.join(impact['components'])}"
            verdict = await self.reviewer(info, told, authors)
            await self.journal.record("review.completed", {"authors": authors, **verdict}, task_id=task_id)
            report["review"] = verdict
            if not verdict.get("skipped") and not verdict.get("approve"):
                rb = await asyncio.to_thread(self.rollback, info)
                await self.journal.record("rollback.created", {"reason": "review rejected the change", "reasons": verdict.get("reasons"), **rb, "snapshot": str(snap)}, task_id=task_id)
                report.update({"outcome": "REVIEW_REJECTED", "rollback": rb, "snapshot": str(snap)})
                return report
        try:
            c = await asyncio.to_thread(self.commit, info, summary, vid)
        except RuntimeError as e:
            await self.journal.record("commit.failed", {"error": str(e)[:500]}, task_id=task_id)
            report.update({"outcome": "COMMIT_FAILED", "error": str(e)})
            return report
        await self.journal.record("commit.created", {"commit": c["commit"], "files": c["files"], "summary": summary, "verification_id": vid}, task_id=task_id)
        report.update({"outcome": "COMMITTED", "commit": c["commit"]})
        if self.autopush:
            await self.journal.record("push.started", {"commit": c["commit"]}, task_id=task_id)
            p = await asyncio.to_thread(self.push)
            await self.journal.record("push.completed" if p["ok"] else "push.failed", p, task_id=task_id)
            report["push"] = p
        else:
            report["push"] = {"ok": None, "output": "not pushed: SYRAX_AUTOPUSH is off; a human pushes"}
        return report


def render(report: Dict[str, Any]) -> str:
    lines = [f"RELEASE {report['outcome']} · verification #{report['verification_id']} {report['verification']}"]
    lines.append("files: " + ", ".join(f"{p} ({s})" for p, s in report["files"].items()))
    lines.append("gates: " + ", ".join(f"{g['name']}={g['status']}" for g in report["gates"]))
    for f in report.get("failing", []):
        lines.append(f"\n--- {f['name']} {f['status']} ---\n{f['evidence']}")
    if report["outcome"] == "ROLLED_BACK":
        rb = report["rollback"]
        lines.append(f"\nRolled back: restored {len(rb['restored'])} file(s), removed {len(rb['removed'])} new file(s); tree clean={rb['clean']}. "
                     f"Snapshot of the attempt: {report['snapshot']}. The same change will fail again: diagnose the evidence and change approach.")
    elif report["outcome"] == "REVIEW_REJECTED":
        # the reviewer's reasons, which the release used to answer with "None" (live 2026-10-15, objective 237)
        rv, rb = report.get("review") or {}, report["rollback"]
        why = "; ".join(rv.get("reasons") or []) or "no reason given"
        if "no_review" in (rv.get("problems") or []):
            lines.append(f"\nNo other brain could review the change ({why}), so it was rolled back unreviewed (restored "
                         f"{len(rb['restored'])} file(s), removed {len(rb['removed'])}). The gate passed and nothing is known to be wrong "
                         f"with it: apply the same change again and release again. Snapshot: {report['snapshot']}.")
        else:
            lines.append(f"\nRolled back: a second brain ({rv.get('reviewer')}) rejected the change ({', '.join(rv.get('problems') or [])}): "
                         f"{why}. Fix what it names, or change approach. Snapshot: {report['snapshot']}.")
    elif report["outcome"] == "COMMITTED":
        lines.append(f"\nCommitted {report['commit'][:12]}. {report['push']['output'] if report['push']['ok'] is None else ('Pushed to ' + report['push']['branch'] if report['push']['ok'] else 'PUSH FAILED: ' + report['push']['output'])}")
    else:
        lines.append(f"\n{report.get('error')}")
    return "\n".join(lines)


class ReleaseTool(BaseTool):
    name: str = "release"
    description: str = (
        "Run the release gate on the code changes you made to SYRAX's own repository (with "
        "str_replace_editor or skill_create) and commit them if it is GREEN, otherwise roll them "
        "back. The gate runs the real test suite, type checks, lint, build and a secret/debug scan; "
        "it takes a minute or two. Nothing outside backend/syrax, backend/skills, frontend, docs "
        "and README can be released this way. Give a one-line summary for the commit message, and for "
        "your own objectives a plan: why (the evidence), risk (what could break), tests (what proves it). "
        "Before calling it, re-read the edited region with str_replace_editor view and make sure "
        "Python still compiles; a release that fails costs two minutes and is rolled back. "
        "If a task ends without a COMMITTED release, all its repository edits are rolled back."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "One line: what changed."},
            "why": {"type": "string", "description": "the evidence or objective this answers"},
            "risk": {"type": "string", "description": "what could break and how you checked"},
            "tests": {"type": "string", "description": "which tests prove it (new or existing)"},
        },
        "required": ["summary"],
    }
    loop: Optional[Any] = Field(default=None, exclude=True)

    async def execute(self, summary: str, why: str = "", risk: str = "", tests: str = "") -> ToolResult:
        if self.loop is None:
            return ToolResult(error="release loop unavailable")
        try:
            report = await self.loop.release(summary, {"why": why, "risk": risk, "tests": tests})
        except ValueError as e:  # the plan was refused (nothing to release, a judge, outside the scope): the guard held
            return ToolResult(error=f"release refused: {e}")
        except (JournalError, RuntimeError) as e:  # something broke (git, the journal): a real failure
            return ToolResult(error=f"release failed: {e}")
        return ToolResult(output=render(report))
