"""SYRAX autonomy: objectives and the bounded self-directed cycle.

    Cycle
      check system (resource gate)
      derive objectives from the self-model's weaknesses (idempotent)
      pick the highest-priority OPEN objective whose dependencies are DONE
      run ONE autonomous task for it through the core (same agent, same tools)
      judge the outcome from JOURNAL EVIDENCE, never from the model's words
      reflect: record what was expected, what happened, what was learned
      next objective on the next cycle, or idle

Bounds: autonomy is OFF unless enabled (journal meta ``autonomy_enabled`` or
``SYRAX_AUTONOMY=1``); at most one task per cycle; a minimum interval between
cycles; an objective is BLOCKED after MAX_ATTEMPTS failed attempts; nothing
runs while a human task is running or the machine is under pressure.

Objective checks (machine-evaluable, evidence from the journal):
  tool_verified {tool}      the tool was used after the objective was created and its last outcome is ok
  verification_green        the newest verification record is GREEN and newer than the objective
  task_success              the objective's own task ended SUCCESS (weakest form of evidence; used for human goals)
  human                     never auto-completed; the objective waits BLOCKED for a person
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.logger import logger

from syrax import resources
from syrax.journal import BACKEND_ROOT, Journal, JournalError

REPO_ROOT_PATH = BACKEND_ROOT.parent

MAX_ATTEMPTS = 3
# Tools that cannot be exercised "harmlessly" without a real need: verifying them
# on their own would mean junk releases, junk skills, fake memories or uncited
# conclusions. Their evidence comes from real use.
NOT_AUTO_VERIFIED = frozenset({
    "release", "skill_create", "skill_test", "learn", "remember", "forget", "experiment", "present", "terminate", "ask_human",
    "compare_versions",
})
DEFAULT_INTERVAL_S = 120.0
# A quality objective is verified by a quality run, which needs an idle core:
# the cycle runs the suite itself, at most this often (free brain quotas).
QUALITY_MEASURE_EVERY_S = 6 * 3600.0
QUALITY_KINDS = ("quality_case_passes", "quality_recovered")
IDLE_INTERVAL_S = 600.0
MAINTENANCE_EVERY_S = 86400.0

AUTONOMOUS_BRIEF = (
    "[AUTONOMOUS OBJECTIVE] You are working on your own objective, not a human request.\n"
    "Goal: {goal}\nReason: {reason}\n{evidence}"
    "Your repository root is {repo_root}; paths in the goal are relative to it. Use absolute paths "
    "with every tool (python_execute runs elsewhere; str_replace_editor requires them). "
    "Read journaled tasks with `self_inspect` task_id and anything else with `journal_query` (read-only SQL), never python/sqlite3.\n"
    "Never weaken a check, test, benchmark or quality case to make it pass: fix the behaviour it measures. "
    "The files that judge or guard you (quality, verify, bench, autonomy, experiments, versions, devloop, "
    "limits, journal, guard, tools) and existing tests are changed only by a human; `release` refuses them here.\n"
    "You cannot run the quality suite or start another SYRAX core from a task (the core is busy with you, "
    "and the journal refuses a second core): fix, `release`, and finish; the next cycle runs the quality suite.\n"
    "Do the work with your tools. Your completion is judged from the journal evidence "
    "(which tools ran and whether they succeeded), not from what you say. Do not claim "
    "success you did not produce. Be economical: every step costs a model call; take the "
    "fewest steps that produce the evidence, do nothing unrelated, and then finish with one "
    "plain sentence stating exactly what you observed.{hint}"
)
BRIEF_HINTS = {
    "skill_verified": " Build it with `skill_create` (code + pytest tests, dependencies listed); the objective closes only when the skill `{name}` is VERIFIED by its own tests. Write files only inside the workspace.",
    "tool_verified": " For this objective one call of the `{tool}` tool with a harmless read-only action is enough; report its output and finish.",
    "knowledge_stored": " Use `research` once on the stated topic, then `learn` one verified conclusion citing the knowledge_ids, then finish.",
    "tool_reliability": " Follow the plan in the goal step by step. The objective closes only when new uses of `{tool}` show the lower failure rate, so finish by using it as the plan says.",
}


@dataclass
class CycleReport:
    started: float
    outcome: str  # RAN | IDLE | SKIPPED | DISABLED | BUSY
    reason: Optional[str] = None
    objective_id: Optional[int] = None
    task_id: Optional[str] = None
    task_status: Optional[str] = None
    verdict: Optional[str] = None  # DONE | RETRY | BLOCKED
    derived: int = 0

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("started", "outcome", "reason", "objective_id", "task_id", "task_status", "verdict", "derived")}


PROPOSAL_KINDS = ("known_limitation", "brain_availability")


def proposal_from(objective: dict, task: Optional[dict]) -> Optional[dict]:
    """Phase 1, "next from what was learned": a researched limitation ends in
    a proposal for the human (what was found, what it would change, sources)
    instead of only a knowledge row nobody reads. SYRAX builds nothing here."""
    lim = ((objective.get("evidence") or {}).get("limitation")) or {}
    text = ((task or {}).get("result") or "").strip()
    if lim.get("kind") not in PROPOSAL_KINDS or not text:
        return None
    return {"objective_id": objective["id"], "limitation": lim.get("detail"), "kind": lim.get("kind"),
            "proposal": text[:1500], "sources": [u.rstrip(".,;:") for u in re.findall(r"https?://[^\s)\]]+", text)][:6]}


def strategy_of(events: List[dict]) -> List[str]:
    """How a task went about it: the distinct tool calls it made, each with
    its most telling argument, in order. Equal lists = the same strategy."""
    out: List[str] = []
    for e in events:
        if e["type"] != "tool.started":
            continue
        p = e["payload"]
        name = p.get("name") or "?"
        if name in ("terminate", "ask_human"):
            continue
        args = p.get("args") or {}
        if name == "python_execute":
            hint = " ".join(str(args.get("code") or "").split())[:40]
        elif name == "str_replace_editor":
            hint = f"{args.get('command')} {str(args.get('path') or '').replace(chr(92), '/').rsplit('/', 1)[-1]}"
        else:
            first = next(iter(args.values()), "") if args else ""
            hint = " ".join(str(first).split())[:40]
        sig = f"{name}({hint})"
        if sig not in out:
            out.append(sig)
    return out[:12]


def past_experience(journal: Journal, objective: dict, limit: int = 3, budget: int = 900) -> str:
    """Phase 5: "last time this approach did badly because X, so this time Y".
    The closed objectives most like this one (same check and subject first,
    then shared goal keywords), with what worked or why they failed."""
    spec = objective.get("check_spec") or {}
    subject = spec.get("tool") or spec.get("case") or spec.get("name") or spec.get("topic")
    words = set(auto_keywords(objective.get("goal") or ""))
    scored = []
    for o in journal.objectives(limit=300, status=["DONE", "BLOCKED", "DROPPED"]):
        if o["id"] == objective.get("id"):
            continue
        ospec = o.get("check_spec") or {}
        osubject = ospec.get("tool") or ospec.get("case") or ospec.get("name") or ospec.get("topic")
        score = (3 if ospec.get("kind") == spec.get("kind") else 0) + (4 if subject and osubject == subject else 0)
        score += len(words & set(auto_keywords(o.get("goal") or "")))
        if score >= 3:
            scored.append((score, o))
    if not scored:
        return ""
    lines = []
    for _, o in sorted(scored, key=lambda x: (-x[0], -x[1]["updated"]))[:limit]:
        prog = o.get("progress") or {}
        log = prog.get("attempts_log") or []
        how = "; ".join((log[-1].get("strategy") or [])[:4]) if log else ""
        lines.append(f"- #{o['id']} {o['status']} after {o.get('attempts', 0)} attempt(s): {str(o['goal'])[:110]} — "
                     f"{str(prog.get('lesson') or '')[:150]}" + (f" (how: {how[:160]})" if how else ""))
    return ("Past experience with similar objectives (repeat what worked, avoid what failed):\n" + "\n".join(lines))[:budget] + "\n"


def brief_evidence(objective: dict, budget: int = 1800) -> str:
    """The evidence the objective was created from, compact, for the task.
    Live: SYRAX was told to "read the failures listed in the evidence" but the
    brief carried only the goal, so it guessed journal tables in raw SQL
    ("no such table: tool_calls", "no such column: id") instead."""
    ev = dict(objective.get("evidence") or {})
    ev.pop("plan", None)  # already in the goal
    log = ((objective.get("progress") or {}).get("attempts_log")) or []
    tried = ""
    if log:
        tried = "Earlier attempts (do not repeat a failed strategy; change the approach):\n" + "\n".join(
            f"- attempt {a.get('attempt')} {a.get('verdict')}: {'; '.join(a.get('strategy') or ['no tools'])[:240]} — {a.get('lesson', '')[:160]}"
            for a in log[-4:]
        ) + "\n"
    if not ev:
        return tried
    lines = []
    for f in ev.pop("recent_failures", []) or []:
        lines.append(f"- task {f.get('task_id')}: {str(f.get('output') or '').strip()[-220:]}")
    head = json.dumps(ev, default=str, ensure_ascii=False)
    text = "Evidence: " + head[: budget // 2] + ("\nRecent failures (read more with self_inspect task_id):\n" + "\n".join(lines) if lines else "")
    return text[:budget] + "\n" + tried


LAUNCHER_PID_FILE = REPO_ROOT_PATH / "syrax.pid"


def _router():
    from syrax.brains import get_router

    return get_router()


def spawn_restart() -> None:
    """Start `syrax.py --respawn`, which starts the real restarter and exits:
    the restarter is then nobody's child, so stopping SYRAX's process tree
    does not kill it."""
    import subprocess
    import sys

    kw = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    subprocess.Popen([sys.executable, str(REPO_ROOT_PATH / "syrax.py"), "--respawn"], cwd=str(REPO_ROOT_PATH),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)


def resource_pressure() -> Optional[str]:
    """A reason string when the machine should not take on extra work, else None.
    Delegates to syrax.resources (CPU, RAM, disk, battery, quiet hours)."""
    return resources.pressure()


def derive_objectives(journal: Journal, selfmodel: Any) -> int:
    """Turn evidence-based weaknesses into objectives. Idempotent via keys."""
    created = 0
    caps = selfmodel.capabilities()
    # a traceback inside SYRAX's own code is a bug SYRAX can fix
    for e in journal.recent_events(300):
        if e["type"] != "tool.failed":
            continue
        out = str(e["payload"].get("output") or "")
        m = TRACE_IN_SYRAX.search(out)
        if not m:
            continue
        tool = e["payload"].get("name") or "?"
        path, line = m.group(1), m.group(2)
        ok = journal.add_objective_sync(
            goal=f"The `{tool}` tool raised inside SYRAX's own code at {path} line {line}: {out.strip().splitlines()[-1][:120]!r}. Read that code, fix the bug, add a new test in backend/syrax if one is missing, and `release`. Then call `{tool}` again the same way to confirm.",
            reason="a traceback in our own code is a defect with a known location",
            priority=2, source="selfmodel",
            check={"kind": "tool_verified", "tool": tool},
            key=f"tool-bug:{tool}:{path}:{line}",
            evidence={"event_id": e["id"], "traceback_tail": out[-600:]},
        )
        created += bool(ok)
    # one live objective per tool: repeated failures must not spawn a new objective each cycle
    targeted = {
        (o.get("check_spec") or {}).get("tool")
        for o in journal.objectives(limit=500, status=["OPEN", "ACTIVE", "BLOCKED"])
        if (o.get("check_spec") or {}).get("kind") == "tool_verified"
    }
    for c in caps:
        name = c["capability"]
        if not c["registered"] or name in NOT_AUTO_VERIFIED or name in targeted:
            continue
        if c["status"] == "NOT_TESTED":
            ok = journal.add_objective_sync(
                goal=f"Verify that the `{name}` tool works on this machine by calling it with a harmless, read-only action and reporting exactly what it returned.",
                reason="no journal evidence that this capability works here",
                priority=5,
                source="selfmodel",
                check={"kind": "tool_verified", "tool": name},
                key=f"verify-capability:{name}",
                evidence={"capability": c},
            )
            created += bool(ok)
        elif c["status"] == "FAILING":
            ok = journal.add_objective_sync(
                goal=f"The `{name}` tool failed on its last use. Diagnose why, then call it again with a harmless action that should succeed and report the result.",
                reason=f"last use failed ({c['failures']}/{c['uses']} failures)",
                priority=2,
                source="selfmodel",
                check={"kind": "tool_verified", "tool": name},
                key=f"repair-capability:{name}:{c['failures']}",
                evidence={"capability": c},
            )
            created += bool(ok)
    # objectives created for such tools by an earlier version are dropped, with the reason
    for o in journal.objectives(limit=500, status=["OPEN", "ACTIVE", "BLOCKED"]):
        spec = o.get("check_spec") or {}
        if spec.get("kind") == "tool_verified" and spec.get("tool") in NOT_AUTO_VERIFIED and o.get("source") == "selfmodel":
            journal.update_objective_sync(o["id"], status="DROPPED", note=f"{spec['tool']} is not auto-verified: it needs a real purpose")
    behavior = selfmodel.behavior()
    last_v = behavior["verifications"]["last"]
    if last_v and last_v["status"] == "BLOCKED":
        failing = [g["name"] for g in last_v["gates"] if g["status"] != "PASS"]
        ok = journal.add_objective_sync(
            goal=f"The last verification run was BLOCKED (failing gates: {', '.join(failing) or 'unknown'}). Investigate the failure output and report the root cause.",
            reason="a blocked gate means the codebase is not releasable",
            priority=1,
            source="selfmodel",
            check={"kind": "verification_green"},
            key=f"verification-blocked:{int(last_v['ts'])}",
            evidence={"verification": last_v},
        )
        created += bool(ok)
    for f in behavior["recent_failures"]:
        topic = _research_topic(f.get("error") or "")
        if topic:
            ok = journal.add_objective_sync(
                goal=f"A task failed with: {str(f.get('error'))[:160]!r}. Research the cause ({topic}) with `research`, store what you learn with `learn`, and say what should change.",
                reason="failure is information; a researched cause beats a blind retry",
                priority=3,
                source="selfmodel",
                check={"kind": "knowledge_stored", "topic": topic},
                key=f"research-failure:{f['task_id']}",
                evidence={"failure": f},
            )
            created += bool(ok)
    # ——— weaknesses of SYRAX's own mechanisms (recursive self-improvement) ———
    bench = journal.benchmarks(limit=1)
    if bench and bench[0]["status"] == "REGRESSION":
        for metric, d in bench[0]["deltas"].items():
            if d.get("regression"):
                ok = journal.add_objective_sync(
                    goal=f"Benchmark metric {metric} regressed from {d['before']} ms to {d['now']} ms ({d['pct']:+.1f}%). Find the cause in SYRAX's own code (journal/self-model/recovery), fix it, and release; the objective closes when a newer benchmark shows no regression for {metric}.",
                    reason="a slower mechanism is a measured weakness, not an opinion",
                    priority=2, source="selfmodel",
                    check={"kind": "benchmark_recovered", "metric": metric},
                    key=f"benchmark-regression:{metric}:{bench[0]['id']}",
                    evidence={"benchmark": {"id": bench[0]["id"], "delta": d}},
                )
                created += bool(ok)
    q = journal.quality_runs(limit=1)
    if q and q[0]["status"] == "REGRESSION":
        failed = [r["id"] for r in q[0]["results"] if not r.get("ok")]
        ok = journal.add_objective_sync(
            goal=f"Task quality regressed to {q[0]['pass_rate']}% ({q[0]['delta']:+.1f} pp); failing cases: {', '.join(failed)}. Inspect those tasks in the journal, find why the outcome was wrong, fix the cause in SYRAX's own code or prompts, release, and run the quality suite again.",
            reason="a lower pass rate on fixed tasks is a measured weakness of SYRAX itself",
            priority=2, source="selfmodel",
            check={"kind": "quality_recovered"},
            key=f"quality-regression:{q[0]['id']}",
            evidence={"quality": {"id": q[0]["id"], "failed": failed, "delta": q[0]["delta"]}},
        )
        created += bool(ok)
    # a quality case that failed in the last two runs is a defect to fix, not a fluke
    runs = journal.quality_runs(limit=2)
    if len(runs) == 2:
        failed_now = {r["id"]: r for r in runs[0]["results"] if not r.get("ok")}
        failed_before = {r["id"] for r in runs[1]["results"] if not r.get("ok")}
        for cid in sorted(set(failed_now) & failed_before):
            r = failed_now[cid]
            why = "; ".join(c["check"] + " → " + str(c.get("detail", ""))[:80] for c in r.get("checks", []) if not c.get("ok"))
            ok = journal.add_objective_sync(
                goal=f"Quality case `{cid}` failed in the last two runs ({why}). Read the case in backend/syrax/quality.py and the journaled task {r.get('task_id')}, find the cause in SYRAX's own behaviour (code or prompts, never the case or its checks), fix it and `release`; the objective closes when a newer quality run passes `{cid}`.",
                reason="a repeatable failure on a fixed task is a defect in SYRAX, not noise",
                priority=2, source="selfmodel",
                check={"kind": "quality_case_passes", "case": cid},
                key=f"quality-case:{cid}:{runs[0]['id']}",
                evidence={"quality_ids": [runs[0]["id"], runs[1]["id"]], "case": r},
            )
            created += bool(ok)
    blocked_tools: Dict[str, int] = {}
    for o in journal.objectives(limit=500, status="BLOCKED"):
        tool = (o.get("check_spec") or {}).get("tool")
        if tool:
            blocked_tools[tool] = blocked_tools.get(tool, 0) + 1
    for tool, n in blocked_tools.items():
        if n >= 2:
            ok = journal.add_objective_sync(
                goal=f"{n} objectives about the `{tool}` tool are BLOCKED after repeated failures. Research a genuinely different approach ({tool} alternative approach) with `research`, store what you find with `learn`, then propose the change.",
                reason="the same strategy failed repeatedly; change the strategy, not the retry count",
                priority=3, source="selfmodel",
                check={"kind": "knowledge_stored", "topic": f"{tool} alternative approach"},
                key=f"strategy-change:{tool}:{n}",
                evidence={"blocked": n},
            )
            created += bool(ok)
    for k in journal.knowledge_recent(limit=200):
        if k["uses"] >= 3 and k["confidence"] < 0.5 and k["kind"] in ("web", "conclusion"):
            ok = journal.add_objective_sync(
                goal=f"Knowledge #{k['id']} is used often ({k['uses']}x) but rests on weak evidence (confidence {k['confidence']:.2f}): {k['claim'][:120]!r}. Corroborate or refute it with `research` (more sources) and store the stronger result.",
                reason="frequently used beliefs deserve stronger evidence",
                priority=4, source="selfmodel",
                check={"kind": "knowledge_confidence", "knowledge_id": k["id"], "min": 0.6},
                key=f"corroborate:{k['id']}",
                evidence={"knowledge": {"id": k["id"], "confidence": k["confidence"], "uses": k["uses"]}},
            )
            created += bool(ok)
    for t in behavior["interrupted"]:
        if t["recovery_state"] == "UNCERTAIN":
            ok = journal.add_objective_sync(
                goal=f"Interrupted task {t['task_id']} ({t['goal'][:80]!r}) has an UNCERTAIN in-flight operation; a human must decide whether to resume or cancel it.",
                reason="never repeat an operation whose completion is unknown",
                priority=2,
                source="selfmodel",
                check={"kind": "human"},
                key=f"uncertain-task:{t['task_id']}",
                status="BLOCKED",
                evidence={"task": t},
                next_action="human: resume or cancel via the UI",
            )
            created += bool(ok)
    return created


def rejudge_blocked(journal: Journal) -> int:
    """BLOCKED objectives with a machine check are judged again on every cycle:
    evidence that arrives later (a quality run, a release, new tool uses) can
    satisfy them. Human checks and plain task_success stay blocked."""
    closed = 0
    for o in journal.objectives(limit=200, status="BLOCKED"):
        kind = (o.get("check_spec") or {}).get("kind", "task_success")
        if kind in ("human", "task_success"):
            continue
        verdict, evidence = judge(journal, o, None)
        if verdict == "DONE":
            journal.update_objective_sync(o["id"], status="DONE", evidence={"judged": evidence, "task_id": None},
                                          progress={"lesson": "evidence that arrived after it was blocked satisfied it"},
                                          note="closed from newer evidence while blocked")
            closed += 1
    return closed


def judge(journal: Journal, objective: dict, task: Optional[dict]) -> tuple[str, dict]:
    """Decide DONE / RETRY from journal evidence only. Returns (verdict, evidence)."""
    spec = objective.get("check_spec") or {}
    kind = spec.get("kind", "task_success")
    if kind == "human":
        return "BLOCKED", {"reason": "requires a human decision"}
    if kind == "tool_verified":
        st = journal.tool_stats().get(spec.get("tool"), None)
        used_after = bool(st and st["last_used"] and st["last_used"] >= objective["created"])
        ok = bool(st and st["last_outcome"] == "ok")
        ev = {"tool": spec.get("tool"), "used_after_objective": used_after, "last_outcome": st["last_outcome"] if st else None, "stats": st}
        return ("DONE" if used_after and ok else "RETRY"), ev
    if kind == "skill_verified":
        # Phase 3: a capability SYRAX built for itself counts only when its own
        # tests made it a VERIFIED tool after the objective was set
        sk = journal.skill(str(spec.get("name") or ""))
        present = bool(sk and sk.get("path") and (Path(sk["path"]) / "skill.py").exists())  # live: VERIFIED in the registry, files deleted
        ok = bool(sk and sk.get("status") == "VERIFIED" and present and (sk.get("last_verified") or 0) >= objective["created"])
        return ("DONE" if ok else "RETRY"), {"skill": spec.get("name"), "status": (sk or {}).get("status"), "files_present": present,
                                            "last_verified": (sk or {}).get("last_verified")}
    if kind == "tool_reliability":
        from syrax.limits import judge_tool_reliability
        return judge_tool_reliability(journal, objective)
    if kind == "knowledge_stored":
        topic_words = set(auto_keywords(spec.get("topic") or ""))
        rows = journal.knowledge_recent(limit=50, since=objective["created"])
        hits = [k for k in rows if topic_words & set(auto_keywords(" ".join([k["claim"], k.get("question") or "", " ".join(k["tags"])])))]
        return ("DONE" if hits else "RETRY"), {"topic": spec.get("topic"), "stored_after_objective": len(rows), "matching": [k["id"] for k in hits][:10]}
    if kind == "quality_case_passes":
        rows = journal.quality_runs(limit=1)
        case = spec.get("case")
        if rows and rows[0]["ts"] >= objective["created"]:
            hit = [r for r in rows[0]["results"] if r["id"] == case]
            ok = bool(hit and hit[0].get("ok"))
            return ("DONE" if ok else "RETRY"), {"case": case, "quality": rows[0]["id"], "passed": ok}
        return "RETRY", {"case": case, "quality": rows[0]["id"] if rows else None, "passed": None}
    if kind == "quality_recovered":
        rows = journal.quality_runs(limit=1)
        ok = bool(rows and rows[0]["ts"] >= objective["created"] and rows[0]["status"] != "REGRESSION")
        return ("DONE" if ok else "RETRY"), {"quality": rows[0]["id"] if rows else None, "status": rows[0]["status"] if rows else None}
    if kind == "benchmark_recovered":
        rows = journal.benchmarks(limit=1)
        ok = bool(rows and rows[0]["ts"] >= objective["created"] and not rows[0]["deltas"].get(spec.get("metric"), {}).get("regression"))
        return ("DONE" if ok else "RETRY"), {"metric": spec.get("metric"), "benchmark": rows[0]["id"] if rows else None, "status": rows[0]["status"] if rows else None}
    if kind == "knowledge_confidence":
        base = journal.knowledge(int(spec.get("knowledge_id") or 0))
        want = float(spec.get("min") or 0.6)
        tags = set((base or {}).get("tags") or [])
        newer = [k for k in journal.knowledge_recent(limit=200, since=objective["created"]) if k["confidence"] >= want and (tags & set(k["tags"]))]
        return ("DONE" if newer else "RETRY"), {"knowledge_id": spec.get("knowledge_id"), "min": want, "stronger": [k["id"] for k in newer][:5]}
    if kind == "change_released":
        commits = [e for e in journal.events_between(objective["created"]) if e["type"] == "commit.created"]
        return ("DONE" if commits else "RETRY"), {"commits": [e["payload"].get("commit") for e in commits][:5]}
    if kind == "verification_green":
        rows = journal.verifications(limit=1)
        ok = bool(rows and rows[0]["status"] == "GREEN" and rows[0]["ts"] >= objective["created"])
        return ("DONE" if ok else "RETRY"), {"verification": rows[0] if rows else None}
    status = (task or {}).get("status")
    return ("DONE" if status == "SUCCESS" else "RETRY"), {"task_status": status, "result": (task or {}).get("result")}


class Autonomy:
    def __init__(self, core: Any, journal: Optional[Journal] = None):
        self.core = core
        self.journal = journal or core.journal
        self.interval = float(os.getenv("SYRAX_CYCLE_INTERVAL", DEFAULT_INTERVAL_S))
        # Phase 1: when idle, rank own limitations and work on the strongest
        self.reflect = os.getenv("SYRAX_REFLECT", "1") != "0"
        self.reports: List[CycleReport] = []
        self._loop_task: Optional[asyncio.Task] = None
        self._cycle_running = False
        self.recover_active("process restarted")

    def recover_active(self, why: str) -> int:
        """An ACTIVE objective with no cycle running is a lie left by a dead or
        cancelled cycle: put it back to OPEN so it can be picked again."""
        n = 0
        for o in self.journal.objectives(limit=500, status="ACTIVE"):
            self.journal.update_objective_sync(o["id"], status="OPEN", note=f"reopened: {why}")
            n += 1
        return n

    # ——— enable / disable (persisted) ———

    @property
    def enabled(self) -> bool:
        env = os.getenv("SYRAX_AUTONOMY")
        if env is not None:
            return env == "1"
        return self.journal.get_meta("autonomy_enabled", "0") == "1"

    def set_enabled(self, on: bool) -> None:
        self.journal.set_meta("autonomy_enabled", "1" if on else "0")
        self.journal.record_sync("autonomy.toggled", {"enabled": on})

    async def set_enabled_async(self, on: bool) -> None:
        await self.journal.run(self.set_enabled, on)

    def status(self) -> dict:
        last = self.reports[-1].to_dict() if self.reports else None
        counts = {st: 0 for st in ("OPEN", "ACTIVE", "DONE", "BLOCKED", "DROPPED")}
        for o in self.journal.objectives(limit=500):
            counts[o["status"]] += 1
        snap = resources.snapshot()
        return {
            "enabled": self.enabled,
            "running_loop": self._loop_task is not None and not self._loop_task.done(),
            "interval_s": self.interval,
            "last_cycle": last,
            "cycles": len(self.reports),
            "objectives": counts,
            "resources": snap,
            "pressure": resources.pressure(snap),
            "last_maintenance": self.journal.get_meta("last_maintenance"),
        }

    # ——— one cycle ———

    def _pick(self) -> Optional[dict]:
        done = {o["id"] for o in self.journal.objectives(limit=500, status="DONE")}
        for o in self.journal.objectives(limit=500, status="OPEN"):
            if all(d in done for d in (o.get("dependencies") or [])):
                return o
        return None

    async def run_once(self, force: bool = False) -> CycleReport:
        """One bounded cycle. ``force`` ignores the enabled flag (manual `cycle_now`)."""
        rep = CycleReport(started=time.time(), outcome="IDLE")
        if not force and not self.enabled:
            rep.outcome, rep.reason = "DISABLED", "autonomy is off"
            return await self._finish(rep)
        if self.core.busy or self._cycle_running:
            rep.outcome, rep.reason = "BUSY", "a task is already running" if self.core.busy else "a cycle is already running"
            return await self._finish(rep)
        self._cycle_running = True
        try:
            return await self._run_cycle(rep, force)
        finally:
            self._cycle_running = False

    async def _run_cycle(self, rep: CycleReport, force: bool) -> CycleReport:
        pressure = resource_pressure()
        if pressure and not force:
            rep.outcome, rep.reason = "SKIPPED", pressure
            return await self._finish(rep)
        if await self._restart_if_pending(rep):
            return await self._finish(rep)
        await self.journal.record("cycle.started", {"forced": force})
        try:
            rep.derived = await self.journal.run(derive_objectives, self.journal, self.core.selfmodel)
        except Exception as e:  # deriving must never kill the cycle
            logger.warning(f"objective derivation failed: {e}")
        try:
            await self.journal.run(rejudge_blocked, self.journal)
        except Exception as e:
            logger.warning(f"re-judging blocked objectives failed: {e}")
        objective = self._pick()
        if objective is None and self.reflect:
            # Phase 1: nothing is failing loudly, so ask what limits SYRAX most
            # and work on that instead of idling.
            try:
                from syrax.limits import choose

                chosen = await self.journal.run(choose, self.journal, self.core.selfmodel)
                if chosen:
                    rep.derived += 1
                    objective = self._pick()
            except Exception as e:  # choosing must never kill the cycle
                logger.warning(f"limitation ranking failed: {e}")
        if objective is None and self.reflect and os.getenv("SYRAX_RADAR", "1") != "0":
            # Phase 6: idle time is when SYRAX looks outward (new models on its brains)
            try:
                from syrax import radar

                if await asyncio.to_thread(radar.due, self.journal):
                    router = _router()
                    found = await radar.scan(router, self.journal)
                    rep.outcome = "RAN"
                    rep.reason = (f"radar: {sum(len(v) for v in found['new'].values())} new model(s), "
                                  f"{len(found['tested'])} tested, baseline for {', '.join(found['baselined']) or 'none'}")
                    return await self._finish(rep)
            except Exception as e:
                logger.warning(f"technology radar failed: {e}")
        if objective is None:
            rep.outcome, rep.reason = "IDLE", "no open objective"
            if self.journal.maintenance_due(MAINTENANCE_EVERY_S):
                # useful idle work: keep the journal bounded (measured, journaled)
                try:
                    m = await self.journal.run(self.journal.maintain)
                    rep.reason = f"no open objective; maintenance: pruned {m['events_pruned']} events, trimmed {m['checkpoint_contexts_trimmed']} contexts"
                except Exception as e:
                    logger.warning(f"maintenance failed: {e}")
            return await self._finish(rep)
        rep.objective_id = objective["id"]
        # Evidence may already satisfy the objective (e.g. the tool ran for another
        # objective). Then there is no work to do: close it, run nothing.
        verdict, evidence = await asyncio.to_thread(judge, self.journal, objective, None)
        if verdict == "DONE":
            await self.journal.update_objective(
                objective["id"], status="DONE", evidence={"judged": evidence, "task_id": None},
                progress={"lesson": "already satisfied by existing evidence; no task needed"},
                note="closed from existing evidence",
            )
            rep.outcome, rep.verdict, rep.reason = "RAN", "DONE", "satisfied by existing evidence"
            return await self._finish(rep)
        if await self._measure_quality(objective, rep):
            return await self._finish(rep)
        await self.journal.update_objective(
            objective["id"], status="ACTIVE",
            progress={"cycle_started": rep.started}, note="cycle picked this objective",
        )
        spec = objective.get("check_spec") or {}
        hint = BRIEF_HINTS.get(spec.get("kind", ""), "").format(**{k: v for k, v in spec.items() if isinstance(v, str)})
        from syrax.devloop import REPO_ROOT

        brief = AUTONOMOUS_BRIEF.format(goal=objective["goal"], reason=objective.get("reason") or "-", hint=hint, repo_root=REPO_ROOT,
                                        evidence=brief_evidence(objective) + past_experience(self.journal, objective))
        task_id = await self.core.submit(brief, said=objective["goal"], session_id=None, kind="autonomous")
        if task_id is None:
            await self.journal.update_objective(objective["id"], status="OPEN", note="core busy")
            rep.outcome, rep.reason = "BUSY", "core refused the task"
            return await self._finish(rep)
        rep.task_id = task_id
        await self.core.wait()
        task = self.journal.task(task_id) or {}
        rep.task_status = task.get("status")
        rep.outcome = "RAN"
        # ——— reflect: expected vs actual, judged from evidence ———
        verdict, evidence = await asyncio.to_thread(judge, self.journal, objective, task)
        rep.verdict = verdict
        attempts = objective["attempts"] + 1
        lesson = _lesson(objective, task, verdict, evidence)
        # Phase 2: remember how this attempt went about it; a strategy that
        # already failed is not tried again (no blind retry)
        strategy = strategy_of(self.journal.events(task_id))
        log = list(((objective.get("progress") or {}).get("attempts_log")) or [])
        repeated = verdict != "DONE" and any(a.get("strategy") == strategy and a.get("verdict") != "DONE" for a in log)
        if repeated:
            lesson = f"repeated the strategy of an earlier failed attempt ({', '.join(strategy[:4]) or 'no tools'}); {lesson}"
        log.append({"attempt": attempts, "task_id": task_id, "verdict": verdict, "strategy": strategy, "lesson": lesson[:300]})
        if repeated:
            verdict = "BLOCKED"
        if verdict == "DONE":
            await self.journal.update_objective(
                objective["id"], status="DONE",
                progress={"lesson": lesson, "attempts_log": log[-6:]}, evidence={"judged": evidence, "task_id": task_id},
                last_task_id=task_id, bump_attempts=True, note=lesson,
            )
            proposal = proposal_from(objective, task)
            if proposal:
                await self.journal.record("proposal.created", {**proposal, "task_id": task_id})  # the task is closed; the event stands alone
        elif verdict == "BLOCKED" or attempts >= MAX_ATTEMPTS:
            rep.verdict = "BLOCKED"
            await self.journal.update_objective(
                objective["id"], status="BLOCKED",
                progress={"lesson": lesson, "attempts_log": log[-6:]}, evidence={"judged": evidence, "task_id": task_id},
                last_task_id=task_id, bump_attempts=True,
                next_action="needs a different strategy or a human", note=lesson,
            )
        else:
            await self.journal.update_objective(
                objective["id"], status="OPEN",
                progress={"lesson": lesson, "attempts_log": log[-6:]}, evidence={"judged": evidence, "task_id": task_id},
                last_task_id=task_id, bump_attempts=True,
                next_action="retry with a changed approach", note=lesson,
            )
        await self.journal.record(
            "reflection.created",
            {"objective_id": objective["id"], "expected": objective["check_spec"], "actual": evidence,
             "task_status": rep.task_status, "verdict": rep.verdict, "lesson": lesson, "attempt": attempts},
            task_id=task_id,
        )
        return await self._finish(rep)

    async def _restart_if_pending(self, rep: CycleReport) -> bool:
        """Close the self-modification loop: a release committed new code, but
        the running process still runs the old one until a restart. When idle
        and launched by syrax.py, restart cleanly into the new commit."""
        if os.getenv("SYRAX_SELF_RESTART", "1") == "0" or getattr(self.core, "busy", False):
            return False
        if not LAUNCHER_PID_FILE.exists():
            return False  # not started by syrax.py (tests, a bare server): nobody would bring it back
        try:
            ident = self.core.selfmodel.identity()
        except Exception:
            return False
        if not ident.get("restart_pending"):
            return False
        await self.journal.record("restart.requested", {"running": ident.get("version"), "on_disk": ident.get("newer_on_disk_not_running")})
        spawn_restart()
        rep.outcome, rep.reason = "RESTARTING", f"new code on disk ({ident.get('newer_on_disk_not_running')}); restarting into it"
        return True

    async def _measure_quality(self, objective: dict, rep: CycleReport) -> bool:
        """Verify step for quality objectives: after an attempt, the cycle runs
        the quality suite instead of another task. True when it measured."""
        spec = objective.get("check_spec") or {}
        runner = getattr(self.core, "quality", None)
        if spec.get("kind") not in QUALITY_KINDS or objective.get("attempts", 0) < 1 or runner is None:
            return False
        last = self.journal.quality_runs(limit=1)
        last_ts = last[0]["ts"] if last else 0.0
        if last_ts >= objective["updated"] or time.time() - last_ts < QUALITY_MEASURE_EVERY_S:
            return False  # already measured since the attempt, or measured too recently
        try:
            row = await runner.run()
        except Exception as e:
            logger.warning(f"scheduled quality run failed: {e}")
            return False
        verdict, evidence = await asyncio.to_thread(judge, self.journal, objective, None)
        rep.outcome, rep.verdict = "RAN", verdict if verdict == "DONE" else None
        rep.reason = f"measured: quality run {row.get('id')} at {row.get('pass_rate')}%"
        if verdict == "DONE":
            await self.journal.update_objective(objective["id"], status="DONE", evidence={"judged": evidence, "task_id": None},
                                                progress={"lesson": "the fix held: verified by a scheduled quality run"}, note=rep.reason)
        else:
            await self.journal.update_objective(objective["id"], status="OPEN", evidence={"judged": evidence, "task_id": None},
                                                next_action="the measured run still fails: change the approach", note=rep.reason)
        return True

    async def _finish(self, rep: CycleReport) -> CycleReport:
        self.reports.append(rep)
        if len(self.reports) > 200:
            self.reports = self.reports[-200:]
        if rep.outcome in ("BUSY", "DISABLED"):
            return rep  # nothing happened; a loop tick every interval must not fill the journal
        try:
            await self.journal.record("cycle.completed", rep.to_dict())
        except Exception as e:
            logger.warning(f"could not journal cycle: {e}")
        return rep

    # ——— background loop ———

    async def loop(self, max_cycles: Optional[int] = None) -> None:
        n = 0
        while max_cycles is None or n < max_cycles:
            n += 1
            try:
                rep = await self.run_once()
            except Exception as e:
                logger.exception("autonomy cycle crashed")
                rep = CycleReport(started=time.time(), outcome="SKIPPED", reason=f"crash: {e}")
                self.reports.append(rep)
            delay = self.interval if rep.outcome == "RAN" else IDLE_INTERVAL_S if rep.outcome == "IDLE" else self.interval
            await asyncio.sleep(delay)

    def start(self) -> None:
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.create_task(self.loop())

    async def stop(self) -> None:
        if self._loop_task is not None and not self._loop_task.done():
            self._loop_task.cancel()
            await asyncio.gather(self._loop_task, return_exceptions=True)
        self._loop_task = None
        if not self._cycle_running:  # a cycle started by cycle_now keeps its objective until it finishes
            await self.journal.run(self.recover_active, "loop stopped")


TRACE_IN_SYRAX = re.compile(r'File "[^"]*?(backend/syrax/[A-Za-z0-9_/]+\.py)", line (\d+)')


def auto_keywords(text: str) -> List[str]:
    from syrax.research import keywords

    return keywords(text)


def _research_topic(error: str) -> Optional[str]:
    """A researchable topic from an error message, or None when it is not
    something the web can explain (aborts, empty errors, journal outages)."""
    err = (error or "").strip()
    if not err or err.startswith("aborted") or "journal unavailable" in err or "All brains failed" in err:
        return None
    m = re.search(r"No module named ['\"]?([\w.]+)", err)
    if m:
        return f"python module {m.group(1)}"
    m = re.search(r"([A-Za-z]+Error|Exception)[:\s]+(.{0,80})", err)
    if m:
        return f"{m.group(1)}: {m.group(2).strip()}"
    words = auto_keywords(err)
    return " ".join(words[:6]) if len(words) >= 2 else None


def _lesson(objective: dict, task: dict, verdict: str, evidence: dict) -> str:
    spec = objective.get("check_spec") or {}
    if verdict == "DONE":
        return f"objective met: {spec.get('kind')} evidence satisfied (task {task.get('status')})"
    if spec.get("kind") == "tool_verified":
        if not evidence.get("used_after_objective"):
            return f"the task never called `{spec.get('tool')}`; a verification objective needs the tool to actually run"
        return f"`{spec.get('tool')}` ran and failed again (last outcome {evidence.get('last_outcome')}); the same approach will not work"
    if spec.get("kind") == "human":
        return "waiting for a human decision"
    if spec.get("kind") == "quality_case_passes":
        return f"no newer quality run passes case {spec.get('case')!r}; fix, release, then run the quality suite"
    if spec.get("kind") == "quality_recovered":
        return "no newer quality run without a regression; fix, release, then run the quality suite"
    if spec.get("kind") == "benchmark_recovered":
        return f"no newer benchmark without a regression in {spec.get('metric')}; run the benchmark after fixing"
    if spec.get("kind") == "knowledge_confidence":
        return "no stronger knowledge with the same tags was stored; research more sources"
    if spec.get("kind") == "change_released":
        return "no commit was created: the change was never released, or the gate rolled it back"
    if spec.get("kind") == "knowledge_stored":
        return f"nothing about {spec.get('topic')!r} was stored; research and `learn` must actually run"
    return f"task ended {task.get('status')} with error {task.get('error')!r}"
