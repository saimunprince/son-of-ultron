"""SYRAX task-quality benchmark: does SYRAX actually do tasks right?

Mechanism benchmarks (syrax.bench) measure speed. This suite runs real tasks
through the real core and brain and checks the OUTCOME by machine: the final
text, which tools ran, what a file contains. Each run stores per-case
evidence and a pass rate, compared with the previous run: BASELINE, PASS or
REGRESSION (pass rate fell by more than REGRESSION_PP percentage points).

It costs model calls (about a minute per case on a slow free brain), so it is
on demand: `quality_run` over WebSocket, the `quality` CLI, or an objective.
It is never part of the release gate.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from syrax.journal import BACKEND_ROOT, Journal, JournalError

REGRESSION_PP = 15.0
WORKSPACE = BACKEND_ROOT / "workspace" / "quality"
CASE_TIMEOUT_S = 240.0


def _cases(ws: Path) -> List[dict]:
    """Machine-checkable tasks. Prompts are plain requests; checks look at evidence only."""
    return [
        {"id": "arith", "prompt": "What is 17*23? Reply with just the number.",
         "checks": [{"kind": "final_regex", "pattern": r"\b391\b"}]},
        {"id": "python", "prompt": "Use python to compute the 20th Fibonacci number (fib(1)=1, fib(2)=1) and tell me the number.",
         "checks": [{"kind": "tool_used", "tool": "python_execute"}, {"kind": "final_regex", "pattern": r"\b6765\b"}]},
        {"id": "file_create", "prompt": f"Create a file at {ws / 'hello.txt'} whose entire content is exactly: HELLO SYRAX",
         "checks": [{"kind": "file_equals", "path": str(ws / "hello.txt"), "text": "HELLO SYRAX"}]},
        {"id": "file_edit", "prompt": f"In the file {ws / 'counter.py'} change the line `count = 1` to `count = 2`. Change nothing else.",
         "prepare": {"write": {str(ws / "counter.py"): "count = 1\nname = 'x'\n"}},
         "checks": [{"kind": "file_equals", "path": str(ws / "counter.py"), "text": "count = 2\nname = 'x'\n"}]},
        {"id": "self_version", "prompt": "Which git version are you running? Use self_inspect and reply with the short hash only.",
         "checks": [{"kind": "tool_used", "tool": "self_inspect"}, {"kind": "final_regex", "pattern": "{git_short}"}]},
        {"id": "desktop_cpu", "prompt": "Using the desktop tool, report how many CPU cores this machine has. Reply with the number.",
         "checks": [{"kind": "tool_used", "tool": "desktop"}, {"kind": "final_regex", "pattern": r"\b{cpu_count}\b"}]},
        {"id": "restraint", "prompt": "Reply with the single word: ready",
         "checks": [{"kind": "no_tools"}, {"kind": "final_regex", "pattern": r"(?i)\bready\b"}, {"kind": "final_max_len", "n": 40}]},
        {"id": "present_table", "prompt": "Use the present tool to show a table with header name,value and two rows: a,1 and b,2. Then say done.",
         "checks": [{"kind": "tool_used", "tool": "present"}]},
        {"id": "know_honest", "prompt": "Use the `know` tool to check your stored knowledge for the word zorbulon, then tell me honestly whether you know anything about it.",
         "checks": [{"kind": "tool_used", "tool": "know"}]},
        {"id": "research_cite", "prompt": "Research in what year SQLite was first released and answer with the year and one source URL.",
         "checks": [{"kind": "tool_used", "tool": "research"}, {"kind": "final_regex", "pattern": r"\b2000\b"}, {"kind": "final_regex", "pattern": r"https?://"}]},
    ]


def _fill(pattern: str, env: Dict[str, str]) -> str:
    for k, v in env.items():
        pattern = pattern.replace("{" + k + "}", re.escape(v) if k != "cpu_count" else v)
    return pattern


def check_case(case: dict, task: dict, events: List[dict], env: Dict[str, str]) -> List[dict]:
    """Evaluate every check against evidence. Returns [{check, ok, detail}]."""
    final = task.get("result") or ""
    tools = [e["payload"].get("name") for e in events if e["type"] == "tool.started"]
    tools = [t for t in tools if t and t != "terminate"]
    out = []
    for c in case["checks"]:
        k = c["kind"]
        if k == "final_regex":
            pat = _fill(c["pattern"], env)
            ok = re.search(pat, final) is not None
            out.append({"check": f"final matches {pat}", "ok": ok, "detail": final[:160]})
        elif k == "tool_used":
            ok = c["tool"] in tools
            out.append({"check": f"tool {c['tool']} used", "ok": ok, "detail": f"tools: {tools}"})
        elif k == "no_tools":
            out.append({"check": "no tools used", "ok": not tools, "detail": f"tools: {tools}"})
        elif k == "final_max_len":
            out.append({"check": f"final ≤ {c['n']} chars", "ok": len(final.strip()) <= c["n"], "detail": f"{len(final.strip())} chars"})
        elif k == "file_equals":
            try:
                text = Path(c["path"]).read_text()
                ok = text == c["text"]
                detail = text[:120]
            except OSError as e:
                ok, detail = False, str(e)
            out.append({"check": f"file {Path(c['path']).name} content", "ok": ok, "detail": detail})
        else:
            out.append({"check": k, "ok": False, "detail": "unknown check kind"})
    if task.get("status") != "SUCCESS":
        out.append({"check": "task SUCCESS", "ok": False, "detail": f"status {task.get('status')}: {task.get('error')}"})
    return out


class QualityRunner:
    def __init__(self, core: Any, journal: Optional[Journal] = None, workspace: Optional[Path] = None, case_timeout: float = CASE_TIMEOUT_S):
        self.core = core
        self.journal = journal or core.journal
        self.ws = Path(workspace or WORKSPACE)
        self.case_timeout = case_timeout

    def env(self) -> Dict[str, str]:
        from syrax.selfmodel import SelfModel

        ident = SelfModel(self.journal).identity()
        return {"git_short": ident.get("version") or "unknown", "cpu_count": str(os.cpu_count() or 1)}

    async def run_case(self, case: dict, env: Dict[str, str]) -> dict:
        for path, text in (case.get("prepare", {}).get("write") or {}).items():
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(text)
        started = time.time()
        task_id = await self.core.submit(case["prompt"], said=case["prompt"], session_id=None, kind="eval")
        if task_id is None:
            return {"id": case["id"], "ok": False, "task_id": None, "ms": 0, "checks": [{"check": "task started", "ok": False, "detail": "core busy"}]}
        try:
            await asyncio.wait_for(self.core.wait(), timeout=self.case_timeout)
        except asyncio.TimeoutError:
            await self.core.cancel()
            await self.core.wait()
        task = self.journal.task(task_id) or {}
        events = self.journal.events(task_id)
        checks = check_case(case, task, events, env)
        steps = task.get("current_step", 0)
        return {"id": case["id"], "ok": all(c["ok"] for c in checks), "task_id": task_id, "status": task.get("status"),
                "steps": steps, "ms": int((time.time() - started) * 1000), "checks": checks, "final": (task.get("result") or "")[:300]}

    async def run(self, only: Optional[List[str]] = None, cases: Optional[List[dict]] = None) -> dict:
        if self.core.busy:
            raise JournalError("a task is running; the quality run needs an idle core")
        self.ws.mkdir(parents=True, exist_ok=True)
        env = self.env()
        all_cases = cases if cases is not None else _cases(self.ws)
        if only:
            all_cases = [c for c in all_cases if c["id"] in set(only)]
        await self.journal.record("quality.started", {"cases": [c["id"] for c in all_cases]})
        results = []
        for case in all_cases:
            results.append(await self.run_case(case, env))
        passed = sum(1 for r in results if r["ok"])
        rate = round(100.0 * passed / len(results), 1) if results else 0.0
        prev = self.journal.quality_runs(limit=1)
        if not prev:
            status, compared_to, delta = "BASELINE", None, None
        else:
            delta = round(rate - prev[0]["pass_rate"], 1)
            status = "REGRESSION" if delta < -REGRESSION_PP else "PASS"
            compared_to = prev[0]["id"]
        brain = None
        try:
            brain = self.core.agent.llm.active if self.core.agent is not None else None
        except Exception:
            brain = None
        row = await self.journal.run(
            self.journal.add_quality_run_sync, results, rate, status, compared_to, delta, brain,
        )
        return row


def format_report(row: dict) -> str:
    lines = [f"QUALITY {row['status']} · {row['pass_rate']}% pass ({sum(1 for r in row['results'] if r['ok'])}/{len(row['results'])})"
             + (f" · vs #{row['compared_to']} {row['delta']:+.1f} pp" if row.get("compared_to") else "") + (f" · brain {row['brain']}" if row.get("brain") else "")]
    for r in row["results"]:
        lines.append(f"  {'PASS' if r['ok'] else 'FAIL':<4} {r['id']:<14} {r.get('steps', 0):>2} step(s) {r['ms']:>7} ms")
        for c in r["checks"]:
            if not c["ok"]:
                lines.append(f"       ✕ {c['check']}: {c['detail'][:120]}")
    return "\n".join(lines)
