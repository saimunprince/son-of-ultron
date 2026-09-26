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
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.logger import logger

from syrax import resources
from syrax.journal import Journal, JournalError

MAX_ATTEMPTS = 3
DEFAULT_INTERVAL_S = 120.0
IDLE_INTERVAL_S = 600.0
MAINTENANCE_EVERY_S = 86400.0

AUTONOMOUS_BRIEF = (
    "[AUTONOMOUS OBJECTIVE] You are working on your own objective, not a human request.\n"
    "Goal: {goal}\nReason: {reason}\n"
    "Do the work with your tools. Your completion is judged from the journal evidence "
    "(which tools ran and whether they succeeded), not from what you say. Do not claim "
    "success you did not produce. When done, or if you cannot proceed, say so plainly."
)


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


def resource_pressure() -> Optional[str]:
    """A reason string when the machine should not take on extra work, else None.
    Delegates to syrax.resources (CPU, RAM, disk, battery, quiet hours)."""
    return resources.pressure()


def derive_objectives(journal: Journal, selfmodel: Any) -> int:
    """Turn evidence-based weaknesses into objectives. Idempotent via keys."""
    created = 0
    caps = selfmodel.capabilities()
    # one live objective per tool: repeated failures must not spawn a new objective each cycle
    targeted = {
        (o.get("check_spec") or {}).get("tool")
        for o in journal.objectives(limit=500, status=["OPEN", "ACTIVE", "BLOCKED"])
        if (o.get("check_spec") or {}).get("kind") == "tool_verified"
    }
    for c in caps:
        name = c["capability"]
        if not c["registered"] or name in ("terminate", "ask_human") or name in targeted:
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
    if kind == "knowledge_stored":
        topic_words = set(auto_keywords(spec.get("topic") or ""))
        rows = journal.knowledge_recent(limit=50, since=objective["created"])
        hits = [k for k in rows if topic_words & set(auto_keywords(" ".join([k["claim"], k.get("question") or "", " ".join(k["tags"])])))]
        return ("DONE" if hits else "RETRY"), {"topic": spec.get("topic"), "stored_after_objective": len(rows), "matching": [k["id"] for k in hits][:10]}
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
        self.reports: List[CycleReport] = []
        self._loop_task: Optional[asyncio.Task] = None
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
        if self.core.busy:
            rep.outcome, rep.reason = "BUSY", "a task is already running"
            return await self._finish(rep)
        pressure = resource_pressure()
        if pressure and not force:
            rep.outcome, rep.reason = "SKIPPED", pressure
            return await self._finish(rep)
        await self.journal.record("cycle.started", {"forced": force})
        try:
            rep.derived = await self.journal.run(derive_objectives, self.journal, self.core.selfmodel)
        except Exception as e:  # deriving must never kill the cycle
            logger.warning(f"objective derivation failed: {e}")
        objective = self._pick()
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
        await self.journal.update_objective(
            objective["id"], status="ACTIVE",
            progress={"cycle_started": rep.started}, note="cycle picked this objective",
        )
        brief = AUTONOMOUS_BRIEF.format(goal=objective["goal"], reason=objective.get("reason") or "-")
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
        if verdict == "DONE":
            await self.journal.update_objective(
                objective["id"], status="DONE",
                progress={"lesson": lesson}, evidence={"judged": evidence, "task_id": task_id},
                last_task_id=task_id, bump_attempts=True, note=lesson,
            )
        elif verdict == "BLOCKED" or attempts >= MAX_ATTEMPTS:
            rep.verdict = "BLOCKED"
            await self.journal.update_objective(
                objective["id"], status="BLOCKED",
                progress={"lesson": lesson}, evidence={"judged": evidence, "task_id": task_id},
                last_task_id=task_id, bump_attempts=True,
                next_action="needs a different strategy or a human", note=lesson,
            )
        else:
            await self.journal.update_objective(
                objective["id"], status="OPEN",
                progress={"lesson": lesson}, evidence={"judged": evidence, "task_id": task_id},
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

    async def _finish(self, rep: CycleReport) -> CycleReport:
        self.reports.append(rep)
        if len(self.reports) > 200:
            self.reports = self.reports[-200:]
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
        await self.journal.run(self.recover_active, "loop stopped")


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
    if spec.get("kind") == "benchmark_recovered":
        return f"no newer benchmark without a regression in {spec.get('metric')}; run the benchmark after fixing"
    if spec.get("kind") == "knowledge_confidence":
        return "no stronger knowledge with the same tags was stored; research more sources"
    if spec.get("kind") == "change_released":
        return "no commit was created: the change was never released, or the gate rolled it back"
    if spec.get("kind") == "knowledge_stored":
        return f"nothing about {spec.get('topic')!r} was stored; research and `learn` must actually run"
    return f"task ended {task.get('status')} with error {task.get('error')!r}"
