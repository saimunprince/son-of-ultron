"""SYRAX self-model: what SYRAX is, what it has, how it has behaved, what it
can do, and where it is weak — generated from evidence, never hand-written.

Sources (conceptual model: Structure + Behavior + Capability + Performance + Failure):
- structure:    docs/system_map.json (audited component map) + live repo
                introspection (git HEAD/branch/dirty/recent commits, file and
                line counts, test files)
- behavior:     the durable journal (tasks by status, recent tasks, failures,
                interrupted tasks, verifications)
- capability:   the agent's registered tools crossed with journal evidence
                (uses, failures, last use, confidence) — status is derived
- runtime:      CPU/RAM/disk/process, brains, running task
- weaknesses:   derived from the above plus the map's own stated limitations

Every field that cannot be measured is None or an explicit "unknown" note.
Nothing here invents a metric.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.tool.base import BaseTool, ToolResult

from syrax.journal import BACKEND_ROOT, Journal

REPO_ROOT = BACKEND_ROOT.parent
SYSTEM_MAP = REPO_ROOT / "docs" / "system_map.json"
NAME = "SYRAX"
STAGE = "foundation: durable journal, core, verification gate, self-model"
PRINCIPLES = [
    "Never claim success without journaled evidence.",
    "Verify reality before resuming interrupted work.",
    "Every change passes the verification gate before it is pushed.",
    "Unknown is a valid state; say it.",
    "The UI observes; the core is the brain.",
]
SECTIONS = ("summary", "identity", "structure", "runtime", "behavior", "capabilities", "weaknesses", "all")
_PROCESS_STARTED = time.time()


def _git(args: List[str], cwd: Path = REPO_ROOT) -> Optional[str]:
    try:
        out = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=3)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def _count_lines(path: Path) -> int:
    try:
        with path.open("rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def _meminfo() -> Dict[str, Optional[int]]:
    try:
        mem = {}
        for ln in Path("/proc/meminfo").read_text().splitlines():
            k, v = ln.split(":", 1)
            mem[k] = int(v.split()[0]) // 1024
        return {"total_mb": mem.get("MemTotal"), "available_mb": mem.get("MemAvailable")}
    except Exception:
        return {"total_mb": None, "available_mb": None}


class SelfModel:
    def __init__(self, journal: Journal, repo_root: Path = REPO_ROOT, system_map: Path = SYSTEM_MAP):
        self.journal = journal
        self.repo_root = repo_root
        self.system_map_path = system_map
        self.tools_provider = None  # callable -> list[str], set by the core once the agent exists
        self.brains_provider = None  # callable -> dict (BrainRouter.describe)
        self.running_provider = None  # callable -> dict|None (Core.snapshot()["running"])

    # ——— identity ———

    def identity(self) -> dict:
        head = _git(["rev-parse", "--short", "HEAD"], self.repo_root)
        return {
            "name": NAME,
            "version": head,  # the code that is actually running; None if git is unavailable
            "stage": STAGE,
            "principles": PRINCIPLES,
            "boot_id": self.journal.boot_id,
            "process_uptime_s": int(time.time() - _PROCESS_STARTED),
        }

    # ——— structure ———

    def system_map(self) -> Optional[dict]:
        try:
            return json.loads(self.system_map_path.read_text())
        except (OSError, ValueError):
            return None

    def structure(self) -> dict:
        smap = self.system_map()
        head = _git(["rev-parse", "HEAD"], self.repo_root)
        branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], self.repo_root)
        status = _git(["status", "--porcelain"], self.repo_root)
        log = _git(["log", "-10", "--format=%h|%ct|%s"], self.repo_root)
        commits = []
        for ln in (log or "").splitlines():
            h, ts, msg = ln.split("|", 2)
            commits.append({"hash": h, "ts": int(ts), "subject": msg})
        areas = {
            "backend/syrax": self.repo_root / "backend" / "syrax",
            "backend/app": self.repo_root / "backend" / "app",
            "frontend/components": self.repo_root / "frontend" / "components",
            "frontend/lib": self.repo_root / "frontend" / "lib",
            "docs": self.repo_root / "docs",
        }
        files: Dict[str, dict] = {}
        for label, path in areas.items():
            if not path.is_dir():
                files[label] = {"files": 0, "lines": 0, "tests": 0}
                continue
            src = [p for p in path.rglob("*") if p.is_file() and p.suffix in (".py", ".ts", ".tsx", ".md", ".json") and "__pycache__" not in p.parts]
            tests = [p for p in src if p.name.startswith("test_") or p.name.endswith(".test.ts")]
            files[label] = {"files": len(src), "lines": sum(_count_lines(p) for p in src), "tests": len(tests)}
        return {
            "repo_root": str(self.repo_root),
            "git": {
                "head": head,
                "branch": branch,
                "dirty_files": None if status is None else len(status.splitlines()),
                "recent_commits": commits,
            },
            "files": files,
            "components": [
                {"component": c.get("component"), "purpose": c.get("purpose"), "code": c.get("code"), "tests": c.get("tests")}
                for c in (smap or {}).get("components", [])
            ],
            "system_map": {"path": str(self.system_map_path), "generated": (smap or {}).get("generated"), "present": smap is not None},
            "skills": [
                {k: r.get(k) for k in ("name", "version", "status", "purpose", "tests_passed", "tests_failed", "last_verified")}
                for r in self.journal.skills()
            ],
        }

    # ——— runtime ———

    def runtime(self) -> dict:
        try:
            load = os.getloadavg()
            load_out: Optional[List[float]] = [round(x, 2) for x in load]
        except OSError:
            load_out = None
        du = shutil.disk_usage(str(self.repo_root))
        journal_size = None
        try:
            journal_size = self.journal.path.stat().st_size
        except OSError:
            pass
        brains = None
        if self.brains_provider is not None:
            try:
                d = self.brains_provider()
                brains = {
                    "active": d.get("active"),
                    "ready": [p["id"] for p in d.get("providers", []) if p.get("status") == "ready"],
                    "cooldown": [p["id"] for p in d.get("providers", []) if p.get("status") == "cooldown"],
                    "needs_key": [p["id"] for p in d.get("providers", []) if p.get("status") == "no-key"],
                }
            except Exception:
                brains = None
        running = None
        if self.running_provider is not None:
            try:
                running = self.running_provider()
            except Exception:
                running = None
        from syrax import resources

        res = resources.snapshot(self.repo_root)
        return {
            "host": platform.node(),
            "os": platform.platform(),
            "python": sys.version.split()[0],
            "pid": os.getpid(),
            "cpu": {"cores": os.cpu_count(), "load_1_5_15": load_out},
            "memory_mb": _meminfo(),
            "disk_gb": {"total": du.total // 2**30, "free": du.free // 2**30},
            "battery": res["battery"],
            "quiet_hours": res["quiet_hours"],
            "pressure": resources.pressure(res),
            "gpu": None,  # not probed; no GPU on the reference machine
            "journal": {"path": str(self.journal.path), "bytes": journal_size},
            "brains": brains,
            "running_task": running,
        }

    # ——— behavior (journal) ———

    def behavior(self) -> dict:
        counts = self.journal.status_counts()
        recent = self.journal.tasks(limit=10)
        failed = self.journal.tasks(limit=10, status=["FAILED", "UNKNOWN"])
        interrupted = self.journal.tasks(limit=10, status="INTERRUPTED")
        verifications = self.journal.verifications(limit=10)
        knowledge = self.journal.knowledge_recent(limit=5)
        total = sum(counts.values())
        done = counts.get("SUCCESS", 0) + counts.get("PARTIAL", 0)
        finished = done + counts.get("FAILED", 0) + counts.get("CANCELLED", 0) + counts.get("UNKNOWN", 0)
        return {
            "tasks_by_status": counts,
            "tasks_total": total,
            "success_rate": (round(done / finished, 3) if finished else None),
            "recent_tasks": [
                {k: t.get(k) for k in ("task_id", "goal", "status", "stage", "current_step", "updated", "error")}
                for t in recent
            ],
            "recent_failures": [
                {"task_id": t["task_id"], "goal": t["goal"], "status": t["status"], "error": t.get("error"), "when": t.get("updated")}
                for t in failed
            ],
            "interrupted": [
                {
                    "task_id": t["task_id"],
                    "goal": t["goal"],
                    "step": t.get("current_step"),
                    "recovery_state": (t.get("recovery") or {}).get("state"),
                    "operation_state": (t.get("recovery") or {}).get("operation_state"),
                }
                for t in interrupted
            ],
            "knowledge": {
                "count": self.journal.count("knowledge"),
                "recent": [{"id": k["id"], "kind": k["kind"], "confidence": k["confidence"], "claim": k["claim"][:120]} for k in knowledge],
            },
            "verifications": {
                "last": (
                    {"status": verifications[0]["status"], "git_head": verifications[0]["git_head"], "ts": verifications[0]["ts"],
                     "gates": [{"name": g.get("name"), "status": g.get("status")} for g in verifications[0]["gates"]]}
                    if verifications else None
                ),
                "green": sum(1 for v in verifications if v["status"] == "GREEN"),
                "blocked": sum(1 for v in verifications if v["status"] == "BLOCKED"),
            },
        }

    # ——— capability registry (tools × evidence) ———

    def capabilities(self) -> List[dict]:
        tools = []
        if self.tools_provider is not None:
            try:
                tools = list(self.tools_provider())
            except Exception:
                tools = []
        stats = self.journal.tool_stats()
        names = sorted(set(tools) | set(stats))
        out = []
        for name in names:
            st = stats.get(name)
            registered = name in tools or not tools  # if no agent yet, we cannot say
            if st is None:
                status, confidence = "NOT_TESTED", None
            elif st["last_outcome"] == "fail":
                status = "FAILING"
                confidence = round(st["successes"] / st["uses"], 3) if st["uses"] else None
            else:
                status = "VERIFIED"
                confidence = round(st["successes"] / st["uses"], 3) if st["uses"] else None
            if not registered:
                status = "MISSING"  # evidence exists but the tool is not registered now
            out.append(
                {
                    "capability": name,
                    "status": status,
                    "registered": registered,
                    "uses": st["uses"] if st else 0,
                    "successes": st["successes"] if st else 0,
                    "failures": st["failures"] if st else 0,
                    "confidence": confidence,
                    "last_used": st["last_used"] if st else None,
                    "last_failed": st["last_failed"] if st else None,
                    "implementation": _implementation_of(name),
                }
            )
        return out

    # ——— weaknesses (derived) ———

    def weaknesses(self, behavior: Optional[dict] = None, capabilities: Optional[List[dict]] = None) -> List[dict]:
        b = behavior or self.behavior()
        caps = capabilities or self.capabilities()
        out: List[dict] = []
        for c in caps:
            if c["status"] == "FAILING":
                out.append({"kind": "capability", "detail": f"{c['capability']} failed on its last use ({c['failures']}/{c['uses']} failures)", "evidence": "journal.tool_stats"})
            elif c["status"] == "NOT_TESTED" and c["registered"]:
                out.append({"kind": "capability", "detail": f"{c['capability']} has never been used; no evidence it works here", "evidence": "journal.tool_stats"})
        for t in b["interrupted"]:
            if t["recovery_state"] == "UNCERTAIN":
                out.append({"kind": "recovery", "detail": f"task {t['task_id']} ({t['goal'][:60]!r}) is interrupted with an UNCERTAIN operation; needs a human", "evidence": "journal.tasks.recovery"})
        if b["verifications"]["last"] and b["verifications"]["last"]["status"] == "BLOCKED":
            out.append({"kind": "verification", "detail": "the last verification run was BLOCKED", "evidence": "journal.verifications"})
        if b["success_rate"] is not None and b["success_rate"] < 0.7 and b["tasks_total"] >= 5:
            out.append({"kind": "behavior", "detail": f"success rate {b['success_rate']} over {b['tasks_total']} tasks", "evidence": "journal.tasks"})
        smap = self.system_map() or {}
        for c in smap.get("components", []):
            for lim in c.get("limitations", []) or []:
                out.append({"kind": "known_limitation", "detail": f"{c.get('component')}: {lim}", "evidence": "docs/system_map.json"})
        return out

    # ——— assembly ———

    def snapshot(self, section: str = "all") -> dict:
        if section not in SECTIONS:
            raise ValueError(f"unknown section {section!r}; one of {', '.join(SECTIONS)}")
        if section == "identity":
            return {"identity": self.identity()}
        if section == "structure":
            return {"structure": self.structure()}
        if section == "runtime":
            return {"runtime": self.runtime()}
        if section == "behavior":
            return {"behavior": self.behavior()}
        if section == "capabilities":
            return {"capabilities": self.capabilities()}
        if section == "weaknesses":
            return {"weaknesses": self.weaknesses()}
        identity = self.identity()
        behavior = self.behavior()
        caps = self.capabilities()
        weak = self.weaknesses(behavior, caps)
        runtime = self.runtime()
        if section == "summary":
            return {
                "generated": time.time(),
                "identity": identity,
                "tasks_by_status": behavior["tasks_by_status"],
                "success_rate": behavior["success_rate"],
                "running_task": runtime["running_task"],
                "interrupted": behavior["interrupted"],
                "last_verification": behavior["verifications"]["last"],
                "knowledge_count": behavior["knowledge"]["count"],
                "capabilities": [
                    {"capability": c["capability"], "status": c["status"], "uses": c["uses"], "confidence": c["confidence"]} for c in caps
                ],
                "weaknesses": [w for w in weak if w["kind"] != "known_limitation"],
                "known_limitations": len([w for w in weak if w["kind"] == "known_limitation"]),
                "runtime": {"cpu": runtime["cpu"], "memory_mb": runtime["memory_mb"], "brains": runtime["brains"]},
            }
        return {
            "generated": time.time(),
            "identity": identity,
            "structure": self.structure(),
            "runtime": runtime,
            "behavior": behavior,
            "capabilities": caps,
            "weaknesses": weak,
        }


def _implementation_of(tool: str) -> str:
    if tool.startswith("browser_"):
        return "browser-use MCP (backend/syrax/browser.py launches Chrome)"
    if tool.startswith("skill_"):
        return "backend/syrax/skills.py"
    return {
        "python_execute": "backend/syrax/tools.py AsyncPythonExecute",
        "str_replace_editor": "backend/app/tool/str_replace_editor.py",
        "desktop": "backend/syrax/desktop.py",
        "remember": "backend/syrax/memory.py",
        "recall": "backend/syrax/memory.py",
        "forget": "backend/syrax/memory.py",
        "ask_human": "backend/syrax/tools.py WebAskHuman",
        "terminate": "backend/app/tool/terminate.py",
        "self_inspect": "backend/syrax/selfmodel.py",
        "research": "backend/syrax/research.py",
        "know": "backend/syrax/research.py",
        "learn": "backend/syrax/research.py",
    }.get(tool, "unknown")


def render(snapshot: dict, limit: int = 12000) -> str:
    text = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(text) > limit:
        text = text[:limit] + "\n…[truncated; ask for a single section]"
    return text


class SelfInspectTool(BaseTool):
    """Lets SYRAX read its own self-model (evidence-based)."""

    name: str = "self_inspect"
    description: str = (
        "Inspect yourself: identity and version, architecture and code layout, runtime "
        "resources, task history and failures from the journal, the capability registry with "
        "evidence, and derived weaknesses. Use it to answer questions about what you are, what "
        "you can do, what failed, or what to improve. Never guess these; call this."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "section": {
                "type": "string",
                "enum": list(SECTIONS),
                "description": "Which part to read. 'summary' is compact; 'all' is everything.",
            }
        },
    }
    model: Optional[Any] = None  # SelfModel, set by the core

    async def execute(self, section: str = "summary") -> ToolResult:
        if self.model is None:
            return ToolResult(error="self-model unavailable (core not started)")
        try:
            snap = self.model.snapshot(section)
        except ValueError as e:
            return ToolResult(error=str(e))
        return ToolResult(output=render(snap))
