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
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from pydantic import Field

from app.tool.base import BaseTool, ToolResult

from syrax.journal import BACKEND_ROOT, Journal, JournalError
from syrax.verify import Gate, Verification, default_gates, run_gates, scan_diff_text

REPO_ROOT = BACKEND_ROOT.parent
# What SYRAX may change on its own. Everything else needs a human commit.
SCOPE = ("backend/syrax/", "backend/skills/", "backend/requirements-syrax.txt", "frontend/components/", "frontend/lib/", "frontend/app/", "docs/", "README.md")
FORBIDDEN = (".env", "config/config.toml", "config/brains.json", "journal.db", ".git/", "node_modules/", ".venv/", ".next/")
SNAPSHOT_DIR = BACKEND_ROOT / "config" / "rollback"


def _git(args: Sequence[str], cwd: Path, timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout)


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


# Tools that can write files anywhere in the repository (paths unknown), and
# the editor, whose edits are journaled path by path (code.changed).
WRITER_TOOLS = frozenset({"python_execute", "skill_create"})
EDITOR_TOOL = "str_replace_editor"


def owned_files(files: Dict[str, str], tools_used: Iterable[str], edited_paths: Iterable[str]) -> Dict[str, str]:
    """Which of the not-baseline changes a task is responsible for, judged from
    what it actually ran. A task that never ran a file-writing tool owns
    nothing (a human editing the tree while it ran is not its doing); a task
    that only used the editor owns exactly the paths it edited; a task that
    ran python or built a skill may have written anywhere, so it owns every
    change that was not there when it started."""
    used = set(tools_used)
    if not used & (WRITER_TOOLS | {EDITOR_TOOL}):
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
    "backend/syrax/devloop.py", "backend/syrax/limits.py", "backend/syrax/plan.py", "backend/syrax/followup.py", "backend/syrax/skills.py", "backend/syrax/skillevo.py",
    # and what guards the evidence: the journal's owner/read-only rules and the
    # python_execute guard (an agent must not take down its own guard rails)
    "backend/syrax/journal.py", "backend/syrax/guard.py", "backend/syrax/_guard_site/sitecustomize.py",
    "backend/syrax/tools.py", "backend/syrax/review.py",
)


def judge_problems(files: Dict[str, str]) -> List[str]:
    """Changes an autonomous task may not release: the judges, and any edit or
    deletion of an existing test (new tests are welcome)."""
    problems = []
    for path, st in files.items():
        name = path.rsplit("/", 1)[-1]
        if path in JUDGES:
            problems.append(f"{path}: this file judges SYRAX's own work; only a human changes it")
        elif (name.startswith("test_") or name.endswith(".test.ts")) and st != "??":
            problems.append(f"{path}: existing tests are the contract; add a new test instead of changing this one")
    return problems


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
                 task_id_provider: Optional[Callable[[], Optional[str]]] = None, snapshot_dir: Optional[Path] = None):
        self.journal = journal
        self.root = Path(root)
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

    def begin_task(self) -> Dict[str, str]:
        """Record the pre-existing working-tree changes when a task starts."""
        try:
            self.baseline = changed_files(self.root)
        except Exception:
            self.baseline = {}
        return dict(self.baseline)

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
        if task and task.get("kind") in ("autonomous", "eval"):
            problems += judge_problems(files)
        if problems:
            raise ValueError("refused: " + "; ".join(problems))
        diff = _git(["diff", "HEAD", "--", *[p for p, st in files.items() if st != "??"]], self.root).stdout if any(st != "??" for st in files.values()) else ""
        untracked_text = ""
        for path, st in files.items():
            if st == "??":
                p = self.root / path
                try:
                    body = p.read_text(errors="replace")
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
                    compile((self.root / path).read_text(errors="replace"), str(path), "exec")  # syntax only, no .pyc written
                except SyntaxError as e:
                    broken.append(f"{path}: line {e.lineno}: {e.msg}")
        if broken:
            raise ValueError("refused: python does not compile — fix it before the gate: " + "; ".join(broken))
        stat = _git(["diff", "HEAD", "--stat", "--", *files], self.root).stdout.strip()
        head = _git(["rev-parse", "HEAD"], self.root).stdout.strip()
        return {"files": files, "diff": diff, "untracked": [p for p, s in files.items() if s == "??"], "stat": stat, "head": head}

    def snapshot(self, info: Dict[str, Any]) -> Path:
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        path = self.snapshot_dir / f"{int(time.time())}-{info['head'][:7]}.patch"
        body = info["diff"]
        for rel in info["untracked"]:
            try:
                body += f"\n# untracked: {rel}\n" + (self.root / rel).read_text(errors="replace")
            except OSError:
                pass
        path.write_text(body)
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
        return {"commit": head, "files": files}

    def push(self) -> Dict[str, Any]:
        branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], self.root).stdout.strip()
        out = _git(["push", "origin", branch], self.root, timeout=120)
        return {"ok": out.returncode == 0, "branch": branch, "output": (out.stdout + out.stderr).strip()[-500:]}

    # ——— the loop ———

    async def release(self, summary: str, plan: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
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
        impact = impact_of(info["files"], self.root)
        await self.journal.record("release.planned", {"summary": summary, "plan": plan, **impact}, task_id=task_id)
        snap = await asyncio.to_thread(self.snapshot, info)
        await self.journal.record(
            "code.changed", {"files": info["files"], "stat": info["stat"], "head": info["head"], "snapshot": str(snap)}, task_id=task_id,
        )
        verification: Verification = await asyncio.to_thread(run_gates, self.gates(), self.journal, task_id)
        vid = self.journal.verifications(limit=1)[0]["id"]
        report: Dict[str, Any] = {
            "summary": summary,
            "files": info["files"],
            "verification_id": vid,
            "verification": verification.status,
            "gates": [{"name": g.name, "status": g.status, "required": g.required} for g in verification.gates],
            "failing": [{"name": g.name, "status": g.status, "evidence": g.evidence[-1500:]} for g in verification.gates if g.required and g.status != "PASS"],
        }
        if verification.status != "GREEN":
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
        except (ValueError, JournalError, RuntimeError) as e:
            return ToolResult(error=f"release refused: {e}")
        return ToolResult(output=render(report))
