"""SYRAX core: the one entity that runs tasks, independent of any UI session.

- Owns the single SyraxAgent and the journal.
- Sessions (WebSocket connections) are observers and command routers only.
  Closing the browser does not cancel work; reconnecting streams the current
  state, the running task's events so far and interrupted tasks.
- Every meaningful agent event goes through the journal (durable first, then
  fanned out to observers). UI-only pulses (``state``) and protocol chatter go
  straight to observers.

Routing rule (``_journal_type``): an event is journaled iff replay or recovery
would need it — think, tool_start, tool_result, ask, answer, final, brain
failover/answered, plus task/checkpoint/recovery/verification events the core
writes itself. Everything else (state, hello, brains, notice, error, pong,
user echo, history replies) is direct.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import re
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, List, Optional

from app.logger import logger
from app.schema import Message

from syrax.agent import SyraxAgent, ToolCrash
from syrax.claims import UNPROVEN_SOFT
from syrax.brains import BrainError, get_router
from syrax import intent, phases, redact
from syrax.devloop import REPO_ROOT, DevLoop, ReleaseTool
from syrax.experiments import ExperimentEngine, ExperimentTool
from syrax.journal import Event, Journal, JournalError, get_journal
from syrax.presentation import PresentTool, PresentationEngine
from syrax.research import KnowTool, LearnTool, Researcher, ResearchTool
from syrax.selfmodel import SelfInspectTool, SelfModel
from syrax.skills import SkillCreateTool, SkillFactory, SkillListTool, SkillTestTool
from syrax.versions import CompareVersionsTool, VersionComparer

Observer = Callable[[dict], Awaitable[None]]

RESUME_NOTE = (
    "[RESUMED AFTER INTERRUPTION] The previous process died while working on this "
    "task at step {step} ({stage}). Operation in flight: {op}. Recovery classified it "
    "as {op_state}. Do not assume that operation ran or did not run: inspect the actual "
    "state (files, outputs) before repeating anything, then continue the task."
)


def _op_summary(op: dict) -> str:
    """The in-flight operation of an interrupted task, short enough for a notice."""
    if not op:
        return "no operation recorded"
    args = repr(op.get("args") or {})
    return f"{op.get('name') or '?'} {args[:120]}{'…' if len(args) > 120 else ''}"


def _journal_type(event: dict) -> Optional[str]:
    t = event.get("type")
    if t == "tool_start":
        return "tool.started"
    if t == "tool_result":
        return "tool.completed" if event.get("ok") else "tool.failed"
    if t == "brain" and event.get("event") in ("failover", "answered"):
        return f"brain.{event['event']}"
    if t == "permission" and event.get("event") in ("authorized", "refused"):
        return f"permission.{event['event']}"
    if t == "claim" and event.get("event") in ("rejected", "uncited"):
        return f"claim.{event['event']}"
    if t == "intent" and event.get("event") in ("recorded", "done", "refused", "uncertain"):
        return f"intent.{event['event']}"  # the intent ledger (intent.py): recovery reads recorded-without-done
    if t == "change" and event.get("event") == "started":
        return "change.started"  # Phase 4: a release task's first repository edit, its covering tests and rollback point
    if t == "plan" and event.get("event") == "replan":
        return "plan.replan"  # Phase 2: REPLAN_STREAK failed calls in a row, the approach must change (agent.REPLAN_NOTE)
    if t == "budget" and event.get("event") == "exhausted":
        return "budget.exhausted"  # mission 2026-10-28: the task's tool-call budget (agent.TOOL_BUDGET) ended it
    if t in ("think", "ask", "final"):
        return t
    return None


@dataclass
class Running:
    task_id: str
    goal: str
    session_id: Optional[str]
    task: Optional[asyncio.Task] = None
    steps: List[dict] = field(default_factory=list)  # completed tool steps, in order
    unjournaled: int = 0
    kind: str = "conversation"
    phase: Optional[str] = None  # F4: understand | plan | act | observe | verify (phases.py)
    tools_run: int = 0
    cancel_reason: str = "aborted by human"  # who or what stopped it, as journaled on task.cancelled


# Live 2026-10-03: right after boot the autonomy cycle and a human "hi" both
# submitted while the agent was still being built (~1 min of MCP connect).
# Both passed the busy check, the cycle never got its task, and its objective
# sat ACTIVE with the cycle hanging. One submit at a time, one agent build at
# a time, and a build that hangs fails instead of freezing SYRAX.
AGENT_CREATE_TIMEOUT_S = float(os.getenv("SYRAX_AGENT_CREATE_TIMEOUT_S", "240"))

# Live 2026-10-25 (audit): every request made while SYRAX worked was answered "Already executing. Stop it
# first." and dropped, voice and HUD included; the journal's PENDING status had waited unused. A human
# request made while a task runs is queued (journaled PENDING) and starts when the running task ends. A
# queued request survives SYRAX's own restarts; one older than this is cancelled with a note, not run late.
QUEUE_STALE_S = float(os.getenv("SYRAX_QUEUE_STALE_S", "3600"))
# Review 2026-10-27: a restart's stop (`syrax.py --stop`/--restart: {"type": "stop", "reason": "shutdown"}) ended the
# running task, and its cleanup started the next queued request a moment before the process was killed; that request
# came back INTERRUPTED, not PENDING, so requeue_after_boot never saw it. A shutdown stop holds the queue: no queued
# request starts for this long (the process is about to die; if it does not, the queue moves on by itself).
QUEUE_HOLD_S = float(os.getenv("SYRAX_QUEUE_HOLD_S", "120"))
# Boot policy for INTERRUPTED tasks (live 2026-10-25, audit "Task runtime"): three sat open for 3-11 days
# until a hand dismissed them. SYRAX restarts itself into new code several times a day, so an interruption
# is routine. A human's conversation that could resume waits this long for the human; an autonomous
# attempt whose in-flight operation is UNCERTAIN waits this long for the human the `uncertain-task:`
# objective asks. See Core.settle_interrupted and docs/EXECUTION_MODEL.md section 7.
SETTLE_CONVERSATION_S = float(os.getenv("SYRAX_SETTLE_CONVERSATION_S", "3600"))
SETTLE_UNCERTAIN_S = float(os.getenv("SYRAX_SETTLE_UNCERTAIN_S", str(7 * 86400)))
# Audit follow-up 2026-10-26: the UI offered RESUME on SYRAX's own interrupted work as on a human's, and Core.resume
# continued it with the previous process's budget and no fresh brief. Own work is never resumed: the resume answers
# with the note (the UI shows it) and dismisses the task the way the boot policy does (Core._dismiss_own_work).
OWN_WORK_NOT_RESUMED = {
    "autonomous": "an autonomous attempt is not resumed; it is dismissed and the objective makes a fresh attempt",
    "eval": "a quality case is run again by the suite, never resumed",
}


def _is_release(goal: str) -> bool:
    """An autonomous brief for an objective that closes only on a landed commit."""
    from syrax.autonomy import RELEASE_MARK

    return RELEASE_MARK in (goal or "")


# Audit 2026-10-25 ("Task runtime"): no task had a wall-clock deadline; only quality cases were cancelled, by the
# quality runner (240/420 s). One deadline per kind, in seconds: a conversation gets 30 min, SYRAX's own autonomous
# work 90 min (a release task runs the gate, ~8 min, and the review inside that), an eval keeps the quality
# runner's own timeouts (None: no core deadline). A task still running when its deadline passes is cancelled
# through the usual cancel path (task.cancelled, error_class "deadline"), and the notice says so.
TASK_DEADLINE_S = {
    "conversation": float(os.getenv("SYRAX_TASK_DEADLINE_S", "1800")),
    "autonomous": float(os.getenv("SYRAX_OWN_TASK_DEADLINE_S", "5400")),
    "eval": None,
}
DEADLINE_REASON = "ran out of time: the task's deadline ({span}) passed"
QUALITY_TIMEOUT_REASON = "the quality case ran out of time"  # quality.py's runner cancels with this text


async def _to_the_end(aw: Awaitable, what: str) -> bool:
    """Run ``aw`` to its end even when the caller is cancelled meanwhile (a task's cleanup must not stop half-way).
    Returns True when a cancel landed on the caller, which should honour it afterwards; an error is logged."""
    inner = asyncio.ensure_future(aw)
    cancelled = False
    while True:
        try:
            await asyncio.shield(inner)
            return cancelled
        except asyncio.CancelledError:
            if inner.done():  # the step itself was cancelled, not the caller
                return cancelled
            cancelled = True
        except Exception as e:
            logger.warning(f"{what} failed: {e}")
            return cancelled


def _span(seconds: float) -> str:
    return f"{seconds / 60:g} min" if seconds >= 60 else f"{seconds:g} s"


def cancel_class(reason: str) -> str:
    """Who or what stopped a task, from its journaled reason: deadline | human | quality_timeout | other."""
    text = reason or ""
    if text.startswith(DEADLINE_REASON.split("{")[0]):
        return "deadline"
    if "by human" in text:
        return "human"
    if QUALITY_TIMEOUT_REASON in text:
        return "quality_timeout"
    return "other"


def error_class(e: BaseException) -> str:
    """Why a task failed: journal | brain | timeout | tool | other (task.failed carries it beside the free text)."""
    if isinstance(e, (sqlite3.Error, JournalError)):
        return "journal"
    cause = e.__cause__ or e
    if isinstance(e, BrainError) or isinstance(cause, BrainError) or "All brains failed" in str(e):
        return "brain"
    if isinstance(e, (asyncio.TimeoutError, TimeoutError)) or isinstance(cause, (asyncio.TimeoutError, TimeoutError)):
        return "timeout"
    if isinstance(e, ToolCrash):
        return "tool"
    return "other"


SHUTDOWN_TIMEOUT_S = 20.0  # each shutdown step (mission 2026-10-28: bounded, never a hang)


class Core:
    def __init__(self, journal: Optional[Journal] = None):
        self.journal = journal or get_journal()
        self.agent: Optional[SyraxAgent] = None
        self.current: Optional[Running] = None
        # the human's conversation, kept aside while SYRAX does its own work
        self._human_context: Optional[list] = None
        self._submit_lock = asyncio.Lock()
        # a task is being started (``_begin``, ``resume``): its coroutine does not exist yet, but SYRAX is busy
        self._starting = 0
        self._agent_lock = asyncio.Lock()
        self.observers: List[Observer] = []
        self.state: dict = {"state": "idle"}  # last direct state event
        self._last_tool_args: dict = {}
        self._queued_requests: dict = {}  # task_id -> (request, said) of queued requests made in this process
        self._queue_hold_until = 0.0  # time.monotonic() before which no queued request starts (hold_queue)
        self._queue_open = False  # a stalled queue may be restarted (after the boot's requeue, or a request queued here)
        self._queue_kick: Optional[asyncio.Task] = None  # the restart of a stalled queue under way (_kick_stalled_queue)
        self._deadline: Optional[asyncio.TimerHandle] = None  # the running task's deadline watchdog (TASK_DEADLINE_S)
        self.journal.subscribe(self._on_journal_event)
        self.selfmodel = SelfModel(self.journal)
        self.selfmodel.tools_provider = self.tool_names
        self.selfmodel.brains_provider = lambda: get_router().describe()
        self.selfmodel.running_provider = lambda: self.snapshot()["running"]
        from syrax.autonomy import Autonomy  # local import: autonomy depends on the core type

        self.autonomy = Autonomy(self)
        self.researcher = Researcher(self.journal, task_id_provider=self.current_task_id)
        self.skills = SkillFactory(self.journal, task_id_provider=self.current_task_id)
        self.devloop = DevLoop(self.journal, task_id_provider=self.current_task_id)
        self.devloop.reviewer = _cross_review
        self.versions = VersionComparer(self.journal, task_id_provider=self.current_task_id)
        self.presentation = PresentationEngine(self.journal, emit=self.broadcast)
        from syrax.presence import Presence

        self.presence = Presence(self.journal)  # Visible Work Presence: visible / minimal / hidden, never touches execution
        try:
            self.presentation.restore()  # the stage survives a restart
        except Exception as e:
            logger.warning(f"stage not restored: {e}")
        from syrax.quality import QualityRunner

        self.quality = QualityRunner(self)
        self.experiments = ExperimentEngine(
            self.journal, lambda: self.agent.available_tools if self.agent else None, task_id_provider=self.current_task_id
        )
        self.journal.subscribe(self.presentation.on_event)

    # ——— observers ———

    def subscribe(self, cb: Observer) -> None:
        if cb not in self.observers:
            self.observers.append(cb)

    def unsubscribe(self, cb: Observer) -> None:
        if cb in self.observers:
            self.observers.remove(cb)

    async def broadcast(self, event: dict) -> None:
        if event.get("type") == "state":
            self.state = {k: v for k, v in event.items() if k != "type"}
        elif event.get("type") == "error" and getattr(self, "presentation", None) is not None:
            await self.presentation.on_direct(event)
        for cb in list(self.observers):
            try:
                await cb(event)
            except Exception as e:
                logger.warning(f"observer failed: {e}")

    async def _on_journal_event(self, ev: Event) -> None:
        await self.broadcast(ev.wire())

    # ——— agent ———

    async def ensure_agent(self) -> SyraxAgent:
        async with self._agent_lock:
            if self.agent is None:
                self.agent = await self._build_agent()
        return self.agent

    async def _build_agent(self) -> SyraxAgent:
        try:
            agent = await asyncio.wait_for(SyraxAgent.create(emit=self.emit), AGENT_CREATE_TIMEOUT_S)
        except asyncio.TimeoutError:
            raise RuntimeError(f"building the agent took over {AGENT_CREATE_TIMEOUT_S:.0f}s (MCP servers not answering)") from None
        self.agent = agent
        agent.checkpoint = self._checkpoint
        if "task_id_provider" in getattr(type(agent), "model_fields", {}):  # memory provenance: `remember` files the task id
            agent.task_id_provider = self.current_task_id
        tools = agent.available_tools
        tool = tools.get_tool("self_inspect")
        if isinstance(tool, SelfInspectTool):
            tool.model = self.selfmodel
        r = tools.get_tool("research")
        if isinstance(r, ResearchTool):
            r.researcher = self.researcher
        k = tools.get_tool("know")
        if isinstance(k, KnowTool):
            k.journal = self.journal
        le = tools.get_tool("learn")
        if isinstance(le, LearnTool):
            le.journal = self.journal
            le.task_id_provider = self.current_task_id
        gh = tools.get_tool("github_search")
        if gh is not None and hasattr(gh, "task_id_provider"):  # github_research.GitHubSearchTool
            gh.journal = self.journal
            gh.task_id_provider = self.current_task_id
        for tname in ("skill_create", "skill_list", "skill_test"):
            st = tools.get_tool(tname)
            if isinstance(st, (SkillCreateTool, SkillListTool, SkillTestTool)):
                st.factory = self.skills
        rt = tools.get_tool("release")
        if isinstance(rt, ReleaseTool):
            rt.loop = self.devloop
        pt = tools.get_tool("present")
        if isinstance(pt, PresentTool):
            pt.engine = self.presentation
            pt.task_id_provider = self.current_task_id
        xt = tools.get_tool("experiment")
        if isinstance(xt, ExperimentTool):
            xt.engine = self.experiments
        vt = tools.get_tool("compare_versions")
        if isinstance(vt, CompareVersionsTool):
            vt.comparer = self.versions
        loaded = self.skills.attach(tools)  # VERIFIED skills from the registry become live tools
        if loaded:
            logger.info(f"registered {loaded} skill(s) from the registry")
        if os.getenv("SYRAX_FEATURES", "0") == "1":
            # prebuilt skills shipped in git are installed and verified like SYRAX's own (off the boot path)
            self._prebuilt = asyncio.ensure_future(self._install_prebuilt())
        return agent

    def current_task_id(self) -> Optional[str]:
        return self.current.task_id if self.current is not None else None

    def tool_names(self) -> List[str]:
        if self.agent is None:
            return []
        return sorted(self.agent.available_tools.tool_map.keys())

    @property
    def busy(self) -> bool:
        """A task runs, or one is being started. Review 2026-10-27: ``busy`` was False while ``_begin`` still awaited
        the agent build, the worktree and the routing, so a RESUME (or a quality run, a forced cycle, a brief proof)
        passed its busy check in that window and a second coroutine drove the same agent."""
        return self._starting > 0 or self._task_running()

    def _task_running(self) -> bool:
        """The running task's coroutine exists and has not ended (what cancel, reset and the deadline act on)."""
        return self.current is not None and self.current.task is not None and not self.current.task.done()

    async def emit(self, event: dict) -> None:
        """The agent's single output port: journal what matters, pass the rest."""
        kind = _journal_type(event)
        if kind is None or self.current is None:
            await self.broadcast(event)
            return
        payload = {k: v for k, v in event.items() if k not in ("type", "image")}
        if kind in ("think", "tool.started", "tool.completed", "tool.failed"):
            # the journal is evidence, not a vault (audit 2026-10-25): a key a tool printed, a key the model passed as an
            # argument or wrote in its reasoning is masked in the record, and so in what the UI shows; the agent's own
            # event is untouched, the model may need the key to do the work
            payload = redact.mask_deep(payload)
        volatile = {"image": event["image"]} if event.get("image") else None
        if kind == "tool.started":
            self._last_tool_args = event.get("args") if isinstance(event.get("args"), dict) else {}
        if kind in ("tool.completed", "tool.failed"):
            self.current.steps.append(
                {"step": event.get("step"), "tool": event.get("name"), "id": event.get("id"), "ok": bool(event.get("ok"))}
            )
        nxt = phases.after(self.current.phase, kind, event, self.current.tools_run)
        if kind == "tool.started":
            self.current.tools_run += 1
        try:
            await self.journal.record(kind, payload, task_id=self.current.task_id, volatile=volatile)
            if nxt is not None:
                self.current.phase = nxt["phase"]
                await self._record_phase(nxt)
            if kind == "tool.completed" and event.get("name") == "str_replace_editor":
                edit = _repo_edit(self.current.steps, self._last_tool_args)
                if edit:
                    await self.journal.record("code.changed", edit, task_id=self.current.task_id)
            if kind in ("tool.completed", "tool.failed") and _observes_window(event.get("name")):
                from syrax.presence import observe_window  # Work Presence: where SYRAX acted, right after it acted

                seen = await asyncio.to_thread(observe_window)
                if seen:
                    await self.journal.record("presence.window", {"tool": event.get("name"), **seen}, task_id=self.current.task_id)
            if kind == "tool.completed" and event.get("name") == "apply_patch":
                for edit in _patch_edits(self.current.steps, self._last_tool_args):  # Phase 3: one code.changed per patched file
                    await self.journal.record("code.changed", edit, task_id=self.current.task_id)
        except (sqlite3.Error, JournalError) as e:
            # Bookkeeping must never kill a task, but we never pretend it was journaled.
            self.current.unjournaled += 1
            logger.warning(f"journal refused {kind} for {self.current.task_id}: {e}")
            await self.broadcast({**event, "unjournaled": True, "task_id": self.current.task_id})

    async def _record_phase(self, payload: dict) -> None:
        """F4: tell the UI about a phase transition. It is not stored: the phase
        is a pure function of the journaled events (phases.path), so the
        journal stays the one record and the past can always be recomputed."""
        if self.current is None:
            return
        await self.broadcast({"type": "phase", "event": "changed", **payload, "task_id": self.current.task_id})

    async def _checkpoint(self, stage: str, verified: Optional[dict] = None, next_action: Optional[str] = None) -> None:
        """A resume point: the agent's exported context goes to the journal, which stores a masked copy of it
        (journal.checkpoint_sync); the agent's live memory keeps the real text."""
        if self.current is None or self.agent is None:
            return
        try:
            await self.journal.checkpoint(
                self.current.task_id,
                stage,
                completed_steps=list(self.current.steps),
                verified=verified or {},
                next_action=next_action,
                context=self.agent.export_context(),
                evidence_state="SUCCESS" if self.current.steps and self.current.steps[-1]["ok"] else "PARTIAL",
            )
        except (sqlite3.Error, JournalError) as e:
            self.current.unjournaled += 1
            logger.warning(f"checkpoint failed for {self.current.task_id}: {e}")

    async def _mark(self, kind: str, payload: dict) -> None:
        """Terminal marks: best effort, logged, never raised (we are in except paths). task.failed and
        task.cancelled always carry an ``error_class`` beside the free text."""
        if self.current is None:
            return
        if kind == "task.failed":
            payload = {"error_class": "other", **payload}
        elif kind == "task.cancelled":
            payload = {"error_class": cancel_class(str(payload.get("error") or "")), **payload}
        try:
            await self.journal.record(kind, payload, task_id=self.current.task_id)
        except (sqlite3.Error, JournalError) as e:
            logger.warning(f"journal {kind} failed for {self.current.task_id}: {e}")

    # ——— commands ———

    async def submit(
        self, goal: str, said: Optional[str], session_id: Optional[str], kind: str = "conversation",
        max_steps: Optional[int] = None, seed: Optional[dict] = None, queue: bool = False,
    ) -> Optional[str]:
        """Start a task. Returns its id, or None when SYRAX is already busy
        (also when another submit got there first while this one waited).
        With ``queue``, a human request (kind conversation) made while SYRAX is busy is not
        refused: it is journaled PENDING, its id is returned, and it starts when the running
        task ends (``_start_next``). SYRAX's own work (eval, autonomous) never queues.
        While the emergency stop is on (syrax.estop), SYRAX's own work does not start at all: None, journaled."""
        from syrax import estop

        if kind in estop.BLOCKED_KINDS and await asyncio.to_thread(estop.active, self.journal):
            await self.journal.record("estop.refused", {"kind": kind, "goal": redact.mask(said or goal)[:200]})
            return None
        async with self._submit_lock:
            if self.busy:
                if not (queue and kind == "conversation"):
                    return None
                task_id = await self.journal.start_task(said or goal, session_id=session_id, kind=kind, pending=True)
                self._queued_requests[task_id] = (goal, said)
                self._queue_open = True
                await self.broadcast({"type": "queue", "items": self.queued()})
                return task_id
            return await self._begin(goal, said, session_id, kind, max_steps, seed)

    def queued(self) -> List[dict]:
        """The waiting human requests, oldest first, with their position (1 = next). Asking also restarts a queue
        that stalled while SYRAX is idle (``_kick_stalled_queue``): its callers (the autonomy cycle, a session's
        hello, the queue panel) are exactly the ones that would otherwise wait on it for ever."""
        items = self._pending()
        if items:
            self._kick_stalled_queue()
        return items

    def _pending(self) -> List[dict]:
        rows = self.journal.tasks(limit=50, status="PENDING")
        # two requests queued in one clock tick (~15 ms on Windows) share `created` and the query's order between them
        # is arbitrary: the queue event's id (a pending row's only event) keeps them in the order they came in
        rows.sort(key=lambda r: (r["created"], r.get("last_event_id") or 0))
        return [{"task_id": r["task_id"], "goal": r["goal"], "created": r["created"], "session_id": r.get("session_id"),
                 "position": i + 1} for i, r in enumerate(rows)]

    def _kick_stalled_queue(self) -> None:
        """Review 2026-10-27: when a queued request failed to start (the agent could not be built after a restart, or
        the request was removed while it was being started) the error was only logged, nothing restarted the queue,
        and the autonomy cycle answered BUSY "a human request is waiting" for ever. An idle core with waiting
        requests starts the oldest one; not before the boot's requeue (stale requests are dropped there first), not
        while the queue is held, not while a submit or a start is under way."""
        if not self._queue_open or self.busy or self.queue_held() or self._submit_lock.locked():
            return
        if self._queue_kick is not None and not self._queue_kick.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._queue_kick = loop.create_task(self._restart_queue())

    async def _restart_queue(self) -> Optional[str]:
        try:
            tid = await self._start_next()
        except Exception as e:
            logger.warning(f"the stalled queue did not restart: {e}")
            return None
        if tid:
            logger.warning(f"the queue had stalled with SYRAX idle; started queued request {tid}")
        return tid

    async def cancel_queued(self, task_id: str, note: str = "removed by human") -> bool:
        # under the submit lock: a removal never lands while _start_next is starting the same request
        async with self._submit_lock:
            row = self.journal.task(task_id)
            if not row or row.get("status") != "PENDING":
                return False
            await self.journal.record("task.cancelled", {"error": f"removed from the queue: {note}"}, task_id=task_id)
            self._queued_requests.pop(task_id, None)
        await self.broadcast({"type": "queue", "items": self._pending()})
        return True

    def hold_queue(self, seconds: float = QUEUE_HOLD_S) -> None:
        """No queued request starts for ``seconds`` (a shutdown stop; QUEUE_HOLD_S). The rows stay PENDING."""
        self._queue_hold_until = max(self._queue_hold_until, time.monotonic() + seconds)

    def queue_held(self) -> bool:
        return time.monotonic() < self._queue_hold_until

    async def _start_next(self) -> Optional[str]:
        """The oldest queued request starts when the core is free and the queue is not held. Returns its id, or None.
        A request that cannot start is settled (cancelled, or failed once it had started, with the reason) and the
        next one is tried: one bad row never stalls the queue behind it."""
        async with self._submit_lock:
            if self.busy or self.queue_held():
                return None
            tried = set()
            while True:
                pending = [q for q in self._pending() if q["task_id"] not in tried]
                if not pending:
                    return None
                nxt = pending[0]
                tried.add(nxt["task_id"])
                # the raw words live in memory; after a restart only the journal's masked copy of the goal is left to run
                goal, said = self._queued_requests.pop(nxt["task_id"], (nxt["goal"], nxt["goal"]))
                try:
                    await self.broadcast({"type": "notice", "text": f"Queued request starting: {str(said or goal)[:80]}"})
                    tid = await self._begin(goal, said, nxt.get("session_id"), "conversation", None, None, task_id=nxt["task_id"])
                except Exception as e:
                    await self._settle_unstarted(nxt["task_id"], e)
                    continue
                await self.broadcast({"type": "queue", "items": self._pending()})
                return tid

    async def _settle_unstarted(self, task_id: str, e: Exception) -> None:
        """A queued request whose start failed: still PENDING -> cancelled with the reason (PENDING cannot fail);
        started (IN_PROGRESS) -> failed; anything else (removed meanwhile) is left as it is."""
        logger.warning(f"queued request {task_id} did not start: {e}")
        status = (self.journal.task(task_id) or {}).get("status")
        why = f"the queued request could not start: {_explain(e)}"
        try:
            if status == "PENDING":
                await self.journal.record("task.cancelled", {"error": why, "error_class": "other"}, task_id=task_id)
            elif status == "IN_PROGRESS":
                await self.journal.record("task.failed", {"error": why, "error_class": error_class(e)}, task_id=task_id)
            else:
                return
        except (sqlite3.Error, JournalError) as je:
            logger.warning(f"could not settle queued request {task_id}: {je}")
            return
        await self.broadcast({"type": "error", "message": why})

    async def requeue_after_boot(self) -> dict:
        """Queued requests survive a restart (SYRAX restarts itself into new code). After recovery a
        young one starts; one older than QUEUE_STALE_S is cancelled with a note rather than run late."""
        now = time.time()
        kept, dropped = [], []
        for q in self._pending():
            age_min = int((now - q["created"]) / 60)
            if now - q["created"] > QUEUE_STALE_S:
                await self.journal.record("task.cancelled", {"error": f"SYRAX restarted before it got to this request (queued {age_min} min ago)"},
                                          task_id=q["task_id"])
                dropped.append(q["task_id"])
            else:
                kept.append(q["task_id"])
        self._queue_open = True  # stale requests are gone: a stalled queue may be restarted from here on
        started = await self._start_next() if kept else None
        return {"kept": kept, "dropped": dropped, "started": started}

    async def _begin(
        self, goal: str, said: Optional[str], session_id: Optional[str], kind: str,
        max_steps: Optional[int], seed: Optional[dict], task_id: Optional[str] = None,
    ) -> str:
        """Start a task now (the caller holds ``_submit_lock`` and knows the core is free). A ``task_id``
        names a queued (PENDING) task to begin; otherwise a new task row is created."""
        self._starting += 1  # busy from here, not only once the coroutine exists
        try:
            return await self._begin_now(goal, said, session_id, kind, max_steps, seed, task_id)
        except BaseException:
            if self.current is not None and self.current.task is None:  # prepared, never launched: nothing runs
                self.current = None
            raise
        finally:
            self._starting -= 1

    async def _begin_now(
        self, goal: str, said: Optional[str], session_id: Optional[str], kind: str,
        max_steps: Optional[int], seed: Optional[dict], task_id: Optional[str],
    ) -> str:
        await self.ensure_agent()
        await asyncio.to_thread(self.devloop.begin_task)  # a task owns only the changes it makes
        if task_id is None:
            task_id = await self.journal.start_task(said or goal, session_id=session_id, kind=kind)  # the row's goal is masked there
        else:  # a queued task starts: the journal's copy of the human's words is masked, the agent gets them raw below
            await self.journal.record("task.started", {"goal": redact.mask(said or goal), "kind": kind}, task_id=task_id)
        from syrax import tools as _tools

        # python_execute confines SYRAX's own work with a kernel write boundary (tools.confinement, 2026-10-28)
        _tools.TASK_KIND, _tools.WRITE_ROOTS = kind, ()
        from syrax import permissions as _permissions

        # the operator's autonomy level bounds what own work may do (permissions.level_needed), read fresh per task
        _permissions.OWN_LEVEL = await asyncio.to_thread(lambda: self.autonomy.level) if kind == "autonomous" else 5
        if kind == "autonomous" and os.getenv("SYRAX_ISOLATE", "0") == "1":
            # M1, isolated evolution: SYRAX's own work happens in a worktree, never in the running tree
            try:
                wt = await asyncio.to_thread(self.devloop.isolate, task_id)
                from syrax import editor as _editor

                _editor.ROOT_MAP = (self.devloop.live_root, wt)
                _tools.WRITE_ROOTS = (wt,)  # its worktree is writable to its code; the live tree and .git are not
                goal = goal + ISOLATION_NOTE.format(worktree=wt, live=self.devloop.live_root)
                await self.journal.record("isolation.started", {"worktree": str(wt)}, task_id=task_id)
                seeded = await asyncio.to_thread(write_seed, wt, seed)
                if seeded:
                    await self.journal.record("repro.seeded", {"files": seeded}, task_id=task_id)
            except Exception as e:
                logger.warning(f"could not isolate task {task_id}: {e}")
                await self.journal.record("isolation.failed", {"error": str(e)[:300]}, task_id=task_id)
        await self._prepare(Running(task_id=task_id, goal=goal, session_id=session_id, kind=kind), said, max_steps)
        if kind in ("eval", "autonomous") and self.agent is not None:
            # Self-contained work: earlier tasks' messages only cost tokens and
            # confuse the model (a quality case once answered "clarify the task"
            # after the previous run's history). System messages stay.
            if self._human_context is None and hasattr(self.agent, "export_context"):
                self._human_context = list(self.agent.export_context() or [])  # kept once, across a run of own tasks
            self.agent.reset_conversation()
        elif self._human_context is not None and self.agent is not None:
            # Live 2026-10-10: Prince said "hi" right after an autonomous task and
            # SYRAX continued that task (edited sysinfo.py, answered with its own
            # step prompt); a conversation task is never rolled back. The human's
            # conversation resumes where the human left it.
            if hasattr(self.agent, "import_context"):
                self.agent.import_context(self._human_context)
            self._human_context = None
        self._launch(goal, said)
        return task_id

    async def _prepare(self, running: Running, said: Optional[str], max_steps: Optional[int] = None) -> None:
        """What a task gets right before its coroutine starts, new or resumed (``_begin`` and ``resume`` both come
        through here; audit follow-up 2026-10-26: a resumed task skipped all of it, so the previous task's budget, a
        release objective's 30 steps, leaked into it, no brain was routed for it and the UI saw no phase): the brain
        routed for the work, ``current`` set in the "understand" phase and the UI told, and the agent's kind, the
        human's own words (not the brief) and a fresh step budget, the agent's default unless the caller sets one."""
        await self._route(said or running.goal, running.task_id, release=running.kind == "autonomous" and _is_release(running.goal))
        running.phase = "understand"
        self.current = running
        await self._record_phase({"phase": "understand", "from": None})
        if self.agent is not None:  # permissions: the kind and the human's own words (not the brief)
            self.agent.task_kind = running.kind
            self.agent.task_goal = said or running.goal
            # a budget is per task: a release objective's 30 steps never leak into the next task
            fields = getattr(type(self.agent), "model_fields", {})
            if "max_steps" in fields:
                self.agent.max_steps = max_steps or fields["max_steps"].default

    def _launch(self, request: str, said: Optional[str]) -> None:
        """Start ``current``'s coroutine and arm its deadline (``_begin`` and ``resume`` both come through here)."""
        assert self.current is not None
        self.current.task = asyncio.create_task(self._run(request, said))
        limit = TASK_DEADLINE_S.get(self.current.kind)
        if limit is not None and limit > 0:
            self._deadline = asyncio.get_running_loop().call_later(limit, self._deadline_passed, self.current.task_id, limit)

    def _deadline_passed(self, task_id: str, limit: float) -> None:
        """The watchdog: the task is still running after its deadline, so it is cancelled with the reason the
        journal and the notice carry. A task that already ended (or a later one) is left alone."""
        self._deadline = None
        if self.current is None or self.current.task_id != task_id or not self._task_running():
            return
        logger.warning(f"task {task_id} ran past its deadline ({_span(limit)}): cancelling")
        self._cancel_now(DEADLINE_REASON.format(span=_span(limit)))

    def _disarm_deadline(self) -> None:
        if self._deadline is not None:
            self._deadline.cancel()
            self._deadline = None

    async def _install_prebuilt(self) -> None:
        from syrax import prebuilt

        try:
            done = await prebuilt.install(self.skills)
            changed = [d for d in done if d.get("outcome") not in ("CURRENT", "KEPT")]
            if changed:
                logger.info("prebuilt skills: " + ", ".join(f"{d['skill']} {d['outcome']}" for d in changed))
        except Exception as e:  # a feature pack never stops SYRAX
            logger.warning(f"prebuilt skills not installed: {e}")

    async def _route(self, text: str, task_id: str, release: bool = False) -> None:
        """Phase 7: try first the brain measured best at this kind of work.
        M2: a release objective's task goes by the code benchmark instead."""
        from syrax import routing

        router = get_router()
        try:
            order = [p for p in router.store.order if router.store.enabled(p)]
            if release:
                kind = "code_change"
                chosen = getattr(router.store, "self_change_brain", None)
                if chosen:
                    # Phase 2: the owner's brain for SYRAX's own code; when it cannot take the call the
                    # benchmark's choice (or the human's order) stands in, and the journal says why
                    ok, why = router.usable(chosen)
                    if ok and chosen in order:
                        router.routed = chosen
                        await self.journal.record("brain.routed", {"kind": kind, "brain": chosen, "instead_of": order[0], "reason": "self_change_brain"}, task_id=task_id)
                        return
                    router.routed = await asyncio.to_thread(routing.preferred_for_code, self.journal, order)
                    await self.journal.record("brain.routed", {"kind": kind, "brain": router.routed or order[0], "instead_of": chosen,
                                                               "reason": f"self_change_brain {chosen} unavailable ({why if ok else why}); fallback"}, task_id=task_id)
                    return
                router.routed = await asyncio.to_thread(routing.preferred_for_code, self.journal, order)
            else:
                kind = routing.kind_of(text)
                router.routed = await asyncio.to_thread(routing.preferred, self.journal, kind, order)
        except Exception as e:  # routing is an optimisation; the human's order always works
            logger.warning(f"routing failed: {e}")
            router.routed = None
            return
        if router.routed:
            await self.journal.record("brain.routed", {"kind": kind, "brain": router.routed, "instead_of": order[0]}, task_id=task_id)

    async def wait(self) -> None:
        """Wait for the running task (if any) to finish. Never raises."""
        if self.current is not None and self.current.task is not None:
            await asyncio.gather(self.current.task, return_exceptions=True)

    async def _run(self, request: str, said: Optional[str]) -> None:
        assert self.agent is not None and self.current is not None
        try:
            reply = await self.agent.run(request)
            await self.journal.record("final", {"text": reply}, task_id=self.current.task_id)
            nxt = phases.after(self.current.phase, "final", {}, self.current.tools_run)
            if nxt is not None:
                self.current.phase = nxt["phase"]
                await self._record_phase(nxt)
            await self._checkpoint("final", verified={"final": True}, next_action=None)
            status = "PARTIAL" if self.agent.step_limit_hit or getattr(self.agent, "loop_stopped", False) else "SUCCESS"
            payload = {"status": status, "result": reply}
            # Mission rule: a claim the agent's checks still reject after their one nudge never completes as SUCCESS
            unproven = getattr(self.agent, "unproven", None)
            if unproven:
                if unproven in UNPROVEN_SOFT:
                    payload["unproven"] = unproven
                else:
                    if status == "SUCCESS":
                        payload["reason"] = "claim_unproven"
                    payload["status"] = "PARTIAL"
                    payload["check"] = unproven
            await self.journal.record("task.completed", payload, task_id=self.current.task_id)
            # conversation history now comes from the journal (tasks of kind
            # "conversation"); history.jsonl is no longer written.
        except asyncio.CancelledError:
            self.agent.repair_memory(aborted=True)
            reason = self.current.cancel_reason
            why = cancel_class(reason)
            await self._mark("task.cancelled", {"error": reason, "error_class": why})
            # a human's stop reads as before; anything else (the deadline, a runner's timeout) says what stopped it
            await self.broadcast({"type": "notice", "text": "Task aborted." if why == "human" else f"Task aborted: {reason}."})
            raise
        except (sqlite3.Error, JournalError) as e:
            # The work may have finished, but we cannot prove it: say so, never claim success.
            logger.exception("SYRAX journal failure during task")
            self.agent.repair_memory()
            await self._mark("task.failed", {"error": f"journal unavailable: {e}", "error_class": "journal"})
            await self.broadcast({"type": "error", "message": f"Journal unavailable: {str(e)[:200]}"})
        except Exception as e:
            logger.exception("SYRAX task failed")
            self.agent.repair_memory()
            await self._mark("task.failed", {"error": _explain(e), "error_class": error_class(e)})
            await self.broadcast({"type": "error", "message": _explain(e)})
        finally:
            self._disarm_deadline()  # the task ended: no timer may outlive it
            # Review 2026-10-27: a cancel that landed here (reset(), a cancelled core.wait(), shutdown) aborted the
            # rollback half-way and left `current` set, no idle and no next request. The cleanup and the idle now run
            # to their end whatever lands meanwhile, and the cancel is honoured afterwards.
            late_cancel = False
            try:
                late_cancel = await _to_the_end(self._clean_repo_after_task(), "the cleanup after the task")
            finally:
                self.current = None
                late_cancel = await _to_the_end(self.broadcast({"type": "state", "state": "idle"}), "the idle state") or late_cancel
            try:
                await self._start_next()  # a human request that waited behind this task (not while the queue is held)
            except Exception as e:  # the queue never takes down the task that just ended
                logger.warning(f"queued request did not start: {e}")
            if late_cancel:
                raise asyncio.CancelledError()

    async def _clean_repo_after_task(self) -> None:
        """Autonomous work may edit SYRAX's own repository, but only `release`
        (gate → commit) may make that permanent. If such a task ends with
        uncommitted edits of its own — step limit, failure, cancel — restore
        those files so a restart can never load half-finished code. Files that
        were already modified before the task (a human's work) and human
        conversations are left alone."""
        from syrax import permissions as _permissions

        _permissions.OWN_LEVEL = 5  # the task is over; the next one reads its own level (core._begin_now)
        if self.current is None or self.current.kind == "conversation":
            return
        if self.devloop.isolated is not None:
            await self._close_worktree()
        try:
            info = await asyncio.to_thread(self._dirty_repo_info)
        except Exception as e:
            logger.warning(f"could not inspect the repository after task: {e}")
            return
        if not info:
            return
        try:
            snap = await asyncio.to_thread(self.devloop.snapshot, info)
            rb = await asyncio.to_thread(self.devloop.rollback, info)
            await self.journal.record(
                "rollback.created",
                {"reason": "task ended without a committed release", **rb, "snapshot": str(snap), "files": info["files"]},
                task_id=self.current.task_id,
            )
            logger.warning(f"rolled back uncommitted edits left by task {self.current.task_id}: {list(info['files'])}")
        except Exception as e:
            logger.error(f"rollback after task failed: {e}")

    async def _close_worktree(self) -> None:
        """M1: the task worked in its own worktree. What it did not release is
        kept as a diff (the next attempt can re-apply it), then the worktree is
        removed. The running tree was never touched."""
        assert self.current is not None
        wt = self.devloop.isolated
        try:
            info = await asyncio.to_thread(self._dirty_repo_info)  # devloop.root is the worktree here
            if info:
                snap = await asyncio.to_thread(self.devloop.snapshot, info)
                await self.journal.record(
                    "rollback.created",
                    {"reason": "task ended without a committed release", "restored": [], "removed": sorted(info["files"]),
                     "clean": True, "snapshot": str(snap), "files": info["files"], "worktree": str(wt)},
                    task_id=self.current.task_id,
                )
        except Exception as e:
            logger.warning(f"could not keep the worktree diff of task {self.current.task_id}: {e}")
        finally:
            from syrax import editor as _editor
            from syrax import tools as _tools

            _editor.ROOT_MAP = None
            _tools.WRITE_ROOTS = ()
            await asyncio.to_thread(self.devloop.discard)

    def _dirty_repo_info(self) -> Optional[dict]:
        from syrax.devloop import _git, changed_files, owned_files

        assert self.current is not None
        files = self.devloop.task_files(changed_files(self.devloop.root))
        if files:  # only what this task's own tools could have written (a human may edit while it runs)
            tools = [s.get("tool") or "" for s in self.current.steps]
            edited = [e["payload"].get("path", "") for e in self.journal.events(self.current.task_id) if e["type"] == "code.changed"]
            files = owned_files(files, tools, edited)
        if not files:
            return None
        tracked = [p for p, st in files.items() if st != "??"]
        return {
            "files": files,
            "diff": _git(["diff", "HEAD", "--", *tracked], self.devloop.root).stdout if tracked else "",
            "untracked": [p for p, st in files.items() if st == "??"],
            "head": _git(["rev-parse", "HEAD"], self.devloop.root).stdout.strip(),
        }

    async def cancel(self, reason: str = "aborted by human") -> bool:
        """Stop the running task. `reason` is journaled: a timeout is not a human
        (live 2026-10-12: a quality case that ran out of time read "aborted by human")."""
        if not self._task_running():
            return False
        self._cancel_now(reason)
        return True

    def _cancel_now(self, reason: str) -> None:
        assert self.current is not None and self.current.task is not None
        self.current.cancel_reason = reason
        self.current.task.cancel()

    async def answer(self, text: str, session_id: Optional[str] = None) -> bool:
        if self.agent is None or not self.agent.ask_tool.answer(text):
            return False
        if self.current is not None:
            try:
                await self.journal.record(
                    "answer", {"text": text, "session_id": session_id}, task_id=self.current.task_id
                )
                return True
            except (sqlite3.Error, JournalError) as e:
                logger.warning(f"journal answer failed: {e}")
        await self.broadcast({"type": "user", "text": text})
        return True

    async def reset(self) -> None:
        for q in self._pending():  # a reset starts over: nothing waits either (and nothing is restarted meanwhile)
            await self.cancel_queued(q["task_id"], note="reset by human")
        if self._task_running():
            assert self.current is not None and self.current.task is not None
            self.current.task.cancel()
            await asyncio.gather(self.current.task, return_exceptions=True)
        if self.agent:
            self.agent.reset_conversation()
        self._human_context = None

    async def resume(self, task_id: str, session_id: Optional[str], force: bool = False, note: str = "") -> Optional[str]:
        """Continue an INTERRUPTED conversation from its last checkpoint. Returns an
        error string (also the note a dismissal answers with), or None when the resume started.

        Live 2026-10-25 (audit): a task whose last operation recovery could not
        verify (UNCERTAIN: a write, code, a page) was resumed by one click like any
        other, and the only protection was RESUME_NOTE asking the model to look
        first. Such a task now starts only on the human's explicit word (``force``
        with a ``note``), journaled as task.resume_forced before the resume.

        Audit follow-up 2026-10-26: SYRAX's own work is never resumed. An autonomous attempt or a quality
        case (OWN_WORK_NOT_RESUMED) is dismissed as the boot policy would dismiss it, journaled, and the
        note comes back for the UI; an UNCERTAIN one still needs force and a note first (dismissing it drops
        the question asked of the human). A conversation gets the preparation a new task gets (``_prepare``)
        on top of its checkpoint context, the resume note and the intent ledger's open sends.

        Review 2026-10-27: a resume checked ``busy`` without ``_submit_lock``, so one made while a submit was still
        starting its task (or a second RESUME from another session) also launched: two coroutines drove one agent.
        A resume now holds the submit lock from the busy check to the launch, and SYRAX is busy meanwhile."""
        async with self._submit_lock:
            if self.busy:
                return "Already executing. Stop it first."
            self._starting += 1
            try:
                return await self._resume_now(task_id, session_id, force, note)
            finally:
                self._starting -= 1

    async def _resume_now(self, task_id: str, session_id: Optional[str], force: bool, note: str) -> Optional[str]:
        """``resume``'s work; the caller holds ``_submit_lock`` and knows the core is free."""
        try:
            ctx = self.journal.resume_context(task_id)
        except JournalError as e:
            return str(e)
        task, cp, recovery = ctx["task"], ctx["checkpoint"], ctx["recovery"]
        op = recovery.get("operation") or {}
        # the intent ledger: sends recorded and never seen to finish (recovery's `intent`, or the journal's open entries)
        open_intents = self.journal.open_intents(task_id)
        external = recovery.get("intent") or (open_intents[-1] if open_intents else None)
        kind = task.get("kind") or "conversation"
        if recovery.get("state") == "UNCERTAIN":
            if not force:
                return (f"task {task_id}'s last operation is UNCERTAIN ({_op_summary(op)}): check what happened first, then "
                        + (f"confirm with force and a note; {OWN_WORK_NOT_RESUMED[kind]}" if kind in OWN_WORK_NOT_RESUMED
                           else "resume with force and a note")
                        + (f"; an external action may have happened: {external.get('summary')}" if external else ""))
            if kind not in OWN_WORK_NOT_RESUMED:  # own work is not resumed, forced or not: nothing to journal as a resume
                await self.journal.record("task.resume_forced", {"note": note, "session_id": session_id}, task_id=task_id)
        if kind in OWN_WORK_NOT_RESUMED:
            return await self._dismiss_own_work(task, session_id, note)
        agent = await self.ensure_agent()
        if cp and cp.get("context"):
            agent.import_context(cp["context"])
        elif self._human_context is not None and hasattr(agent, "import_context"):
            agent.import_context(self._human_context)  # no checkpoint: the human's conversation, not own work's
        # Review 2026-10-27: the human's conversation kept aside while SYRAX did its own work stayed set after a
        # resume, and the next human message (_begin) imported it over the resumed conversation. The resumed
        # conversation is now the human's conversation.
        self._human_context = None
        agent.repair_memory()
        resume_note = RESUME_NOTE.format(
            step=task.get("current_step"),
            stage=task.get("stage"),
            op=(f"{op.get('name')} {op.get('args')}" if op else "none"),
            op_state=recovery.get("operation_state", "UNKNOWN"),
        )
        if external:  # even with force: the model is told, and the agent's ledger refuses the same send again (HELD)
            resume_note += " " + intent.RESUME_NOTE.format(summary=external.get("summary") or external.get("tool") or "?")
        agent.memory.add_message(Message.system_message(resume_note))
        agent.inherited_intents = {intent.key(i.get("tool"), i["args_hash"]): {**i, "done": False} for i in open_intents if i.get("args_hash")}
        if external and external.get("args_hash"):
            agent.inherited_intents.setdefault(intent.key(external.get("tool"), external["args_hash"]), {**external, "done": False})
        await self.journal.mark_resumed(task_id, session_id)
        await asyncio.to_thread(self.devloop.begin_task)
        steps = list((cp or {}).get("completed_steps") or [])
        # the agent's memory is the checkpoint's context (above), not the human context kept aside for own work
        await self._prepare(Running(task_id=task_id, goal=task["goal"], session_id=session_id, kind=kind, steps=steps, tools_run=len(steps)), None)
        request = f"Continue the interrupted task: {task['goal']}"
        self._launch(request, None)  # a resumed task gets its kind's deadline too
        return None

    async def _dismiss_own_work(self, task: dict, session_id: Optional[str], note: str) -> str:
        """A RESUME on SYRAX's own interrupted work: the task is dismissed the way the boot policy dismisses it
        (``settle_interrupted``), now, journaled as task.cancelled with the answer as its note (the human's note and
        session beside it); an autonomous attempt's objective still ACTIVE for it goes back to OPEN, and an UNCERTAIN
        attempt, which the human confirmed with force, loses its ``uncertain-task`` question too, as a DISMISS would.
        Returns the answer the UI shows in place of a resume."""
        kind = task.get("kind") or "conversation"
        why = OWN_WORK_NOT_RESUMED[kind]
        payload = {"error": why}
        if note:
            payload["note"] = note
        if session_id:
            payload["session_id"] = session_id
        await self.journal.record("task.cancelled", payload, task_id=task["task_id"])
        if kind == "autonomous":
            uncertain = (task.get("recovery") or {}).get("state") == "UNCERTAIN"
            await self._release_objectives_of(task, why, drop_uncertain=uncertain, where="on resume")
        return why

    async def auto_resume(self) -> List[str]:
        """Boot-time resume of RESUMABLE conversations, only when SYRAX_AUTO_RESUME=1.
        UNCERTAIN operations are never resumed without a human; SYRAX's own work is never resumed."""
        if os.getenv("SYRAX_AUTO_RESUME", "0") != "1":
            return []
        started: List[str] = []
        for t in self.journal.tasks(limit=50, status="INTERRUPTED"):
            rec = t.get("recovery") or {}
            if rec.get("state") != "RESUMABLE" or self.busy or t.get("kind") in OWN_WORK_NOT_RESUMED:
                continue  # own work is the boot policy's (settle_interrupted), never resumed
            if await self.resume(t["task_id"], None) is None:
                started.append(t["task_id"])
        return started

    async def settle_interrupted(self, now: Optional[float] = None) -> dict:
        """Boot policy for INTERRUPTED tasks, run after auto_resume and before the queue restarts
        (live 2026-10-25: an eval case cut by a restart and two autonomous attempts superseded by later
        commits sat open for 3-11 days until a hand dismissed them). Each decision is journaled as
        ``task.cancelled {"error": <note>}`` or the task is left alone:

        - eval: dismissed; the quality suite runs the case again, it never resumes one.
        - autonomous, RESUMABLE or BLOCKED: dismissed; the objective makes a fresh attempt, and an
          objective still ACTIVE for this task goes back to OPEN.
        - autonomous, UNCERTAIN: kept while younger than SETTLE_UNCERTAIN_S (the ``uncertain-task:``
          BLOCKED objective asks a human); older: dismissed and that objective DROPPED with the same note.
        - conversation, RESUMABLE or BLOCKED: kept while younger than SETTLE_CONVERSATION_S (the human
          may resume it; hello.interrupted shows it); older: dismissed as too old to continue safely.
        - conversation, UNCERTAIN: kept for the human, whatever its age; it is their work.
        Returns {"dismissed": [...], "kept": [...]} (task_id, kind, recovery_state, note/why)."""
        now = time.time() if now is None else float(now)
        dismissed: List[dict] = []
        kept: List[dict] = []
        for t in self.journal.tasks(limit=500, status="INTERRUPTED"):
            state = (t.get("recovery") or {}).get("state") or "UNKNOWN"
            entry = {"task_id": t["task_id"], "kind": t.get("kind"), "recovery_state": state}
            decision = _settle_decision(t, now)
            if decision is None:
                kept.append({**entry, "why": _settle_kept_why(t)})
                continue
            note, drop_uncertain = decision
            await self.journal.record("task.cancelled", {"error": note}, task_id=t["task_id"])
            if t.get("kind") == "autonomous":
                await self._release_objectives_of(t, note, drop_uncertain)
            dismissed.append({**entry, "note": note})
        if dismissed or kept:
            logger.warning(
                "boot policy for interrupted tasks: dismissed "
                + (", ".join(f"{d['task_id']} ({d['kind']} {d['recovery_state']}: {d['note']})" for d in dismissed) or "none")
                + "; kept "
                + (", ".join(f"{k['task_id']} ({k['kind']} {k['recovery_state']}: {k['why']})" for k in kept) or "none")
            )
        return {"dismissed": dismissed, "kept": kept}

    async def _release_objectives_of(self, task: dict, note: str, drop_uncertain: bool, where: str = "at boot") -> None:
        """A dismissed autonomous task leaves no objective pointing at it: one still ACTIVE for this task
        (its last_task_id, or the goal the cycle submitted as the task's goal; the cycle sets last_task_id
        only when the task ends) goes back to OPEN, and with ``drop_uncertain`` the ``uncertain-task:<id>``
        objective that asked a human is DROPPED. ``where`` names the occasion in the objectives' notes: the
        boot policy's "at boot", a RESUME's "on resume"."""
        tid = task["task_id"]
        for o in await asyncio.to_thread(self.journal.objectives, 500, ["OPEN", "ACTIVE", "BLOCKED"]):
            if o.get("status") == "ACTIVE" and (o.get("last_task_id") == tid or o.get("goal") == task.get("goal")):
                await self.journal.update_objective(o["id"], status="OPEN", note=f"task {tid} dismissed {where}: {note}")
            elif drop_uncertain and o.get("key") == f"uncertain-task:{tid}":
                await self.journal.update_objective(o["id"], status="DROPPED", note=f"task {tid} dismissed {where}: {note}")

    # ——— snapshot for (re)connecting observers ———

    def snapshot(self) -> dict:
        running = None
        if self._task_running() and self.current is not None:
            row = self.journal.task(self.current.task_id) or {}
            running = {
                "task_id": self.current.task_id,
                "goal": self.current.goal,
                "stage": row.get("stage"),
                "step": row.get("current_step", 0),
                "status": row.get("status"),
                "phase": self.current.phase,
                "kind": self.current.kind,  # whose work it is (the HUD labels SYRAX's own objectives)
            }
        interrupted = [
            _interrupted_summary(t) for t in self.journal.tasks(limit=10, status="INTERRUPTED")
        ]
        return {
            "state": dict(self.state),
            "running": running,
            "queue": self.queued(),
            "interrupted": interrupted,
            "recent": [_task_summary(t) for t in self.journal.tasks(limit=10)],
            "presentation": self.presentation.plan(),
            "presence": self.presence.snapshot(),
        }

    async def shutdown(self, timeout: float = SHUTDOWN_TIMEOUT_S) -> None:
        """Stop scheduling, cancel the running task, close the agent, and journal the final state (system.shutdown).
        Bounded (mission 2026-10-28): a step that hangs past ``timeout`` is abandoned and named in the record."""
        self.hold_queue(float("inf"))  # the task cancelled below must not start a queued request on its way out
        cancelled = self.current.task_id if self._task_running() and self.current is not None else None
        late: List[str] = []

        async def bounded(name: str, coro) -> None:
            try:
                await asyncio.wait_for(coro, timeout)
            except asyncio.TimeoutError:
                late.append(name)
            except Exception as e:  # a failing step must not keep the rest from closing
                late.append(f"{name}: {type(e).__name__}")

        await bounded("autonomy", self.autonomy.stop())
        if self._task_running():
            assert self.current is not None and self.current.task is not None
            self.current.task.cancel()
            await bounded("task", asyncio.gather(self.current.task, return_exceptions=True))
        if self.agent is not None:
            await bounded("agent", self.agent.shutdown())
            self.agent = None
        try:
            await self.journal.record("system.shutdown", {
                "cancelled_task": cancelled, "autonomy_state": (getattr(self.autonomy, "state", None) or {}).get("state"),
                "queue_held": self.queue_held(), "late": late})
        except Exception as e:
            logger.warning(f"could not journal the shutdown: {e}")
        self.journal.unsubscribe(self._on_journal_event)
        self.journal.unsubscribe(self.presentation.on_event)

    async def note_running_release(self, head: Optional[str]) -> Optional[dict]:
        """At boot: when this process runs the commit SYRAX's own last release created, record release.live once
        (mission 2026-10-28: "committed" and "running after a restart" are different facts; neither is "improved")."""
        if not head:
            return None
        last = next((e for e in reversed(await asyncio.to_thread(self.journal.recent_events, 3000)) if e["type"] == "commit.created"), None)
        if not last or str(last["payload"].get("commit") or "") != head:
            return None
        if any(e["type"] == "release.live" and e["payload"].get("commit") == head
               for e in await asyncio.to_thread(self.journal.recent_events, 3000)):
            return None
        rec = {"commit": head, "released_by_task": last.get("task_id"), "boot_pid": os.getpid(),
               "verified": "the core started on this commit and opened the journal; behaviour is measured separately"}
        await self.journal.record("release.live", rec)
        return rec


async def _cross_review(info: dict, summary: str, authors: List[str]) -> dict:
    if os.getenv("SYRAX_REVIEW", "1") == "0":
        return {"skipped": "SYRAX_REVIEW=0"}
    from syrax.brains import get_router
    from syrax.review import review

    return await review(get_router(), info, summary, authors)


SEED_PATH = re.compile(r"^backend/syrax/test_[a-z0-9_]+\.py$")


def write_seed(worktree: Path, seed: Optional[dict]) -> List[str]:
    """Write a brief's proven test into the task's worktree: only a new backend/syrax/test_*.py, UTF-8 with LF,
    never over an existing file. The release still holds it to the filed sha256 (repro.release_problems);
    this only spares the model retyping it (live 2026-10-19: 2431cec and ad9cd44 lost a brief test that way)."""
    written = []
    for rel, text in (seed or {}).items():
        if not isinstance(rel, str) or not isinstance(text, str) or not SEED_PATH.match(rel):
            continue
        target = Path(worktree) / rel
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((text.replace("\r\n", "\n").rstrip("\n") + "\n").encode("utf-8"))
        written.append(rel)
    return written


ISOLATION_NOTE = (
    "\n\n[ISOLATED WORKTREE] This task works in its own copy of the repository at {worktree}. "
    "str_replace_editor maps every path under {live} there by itself, so keep using the usual paths. "
    "python_execute cannot write into {live} (it is read-only while you work), and tests run with python_execute "
    "would import the running code, not your copy, so do not test that way: `release` runs the full test suite "
    "on your copy, then gates, commits and fast-forwards the running tree. Only `release` moves your change in."
)


def _repo_edit(steps: List[dict], args: dict) -> Optional[dict]:
    """A str_replace_editor edit inside SYRAX's own repository → code.changed payload."""
    cmd = str(args.get("command") or "")
    if cmd not in ("create", "str_replace", "insert", "undo_edit"):
        return None
    raw = str(args.get("path") or "")
    if not raw:
        return None
    if not os.path.isabs(raw.strip().strip('"').strip("'")):
        from syrax.editor import resolve_path
        try:
            raw = str(resolve_path(raw, cmd)[0])  # the editor resolves relative paths the same way
        except Exception:
            return None
    from syrax import editor as _editor

    step = steps[-1].get("step") if steps else None
    if _editor.ROOT_MAP is not None:  # M1: the edit went into the task's worktree; its path is relative to that copy
        wt = _editor.ROOT_MAP[1]
        target = str(_editor.redirect(Path(os.path.realpath(raw))))
        try:
            rel = os.path.relpath(os.path.realpath(target), os.path.realpath(str(wt)))
        except ValueError:
            rel = ".."
        if not rel.startswith(".."):
            return {"path": rel, "command": cmd, "step": step, "isolated": True}
    try:
        rel = os.path.relpath(os.path.realpath(raw), os.path.realpath(str(REPO_ROOT)))
    except ValueError:
        return None
    if rel.startswith(".."):
        return None
    return {"path": rel, "command": cmd, "step": step}


def _observes_window(tool) -> bool:
    from syrax.presence import observes

    return observes(str(tool or ""))


def _patch_edits(steps: List[dict], args: dict) -> List[dict]:
    """apply_patch's touched files → code.changed payloads (repository-relative, as the diff names them)."""
    from syrax import editor as _editor
    from syrax.selfedit import diff_paths

    step = steps[-1].get("step") if steps else None
    out = []
    for rel in diff_paths(str(args.get("diff") or "")):
        edit = {"path": rel, "command": "patch", "step": step}
        if _editor.ROOT_MAP is not None:
            edit["isolated"] = True
        out.append(edit)
    return out


def _task_summary(t: dict) -> dict:
    return {
        k: t.get(k)
        for k in (
            "task_id", "goal", "kind", "status", "stage", "current_step",
            "created", "updated", "result", "error", "last_checkpoint_id",
        )
    }


def _interrupted_summary(t: dict) -> dict:
    rec = t.get("recovery") or {}
    op = rec.get("operation") or {}
    return {
        "task_id": t["task_id"],
        "goal": t["goal"],
        "step": t.get("current_step", 0),
        "stage": t.get("stage"),
        "tool": op.get("name"),
        "question": (op.get("args") or {}).get("inquire") if op.get("name") == "ask_human" else None,
        "recovery_state": rec.get("state", "UNKNOWN"),
        "operation_state": rec.get("operation_state"),
        # the intent ledger: {tool, args_hash, summary, step} of a send that may have gone out (EXTERNAL_UNCERTAIN), else None
        "intent": rec.get("intent"),
        "when": t.get("updated"),
    }


def _settle_age_s(t: dict, now: float) -> float:
    """Seconds since the task was interrupted: recovery stamps ``updated`` when it marks the row
    INTERRUPTED and nothing else touches the row until a resume or a dismissal."""
    return max(0.0, now - float(t.get("updated") or t.get("created") or now))


def _settle_decision(t: dict, now: float) -> Optional[tuple]:
    """The boot policy for one INTERRUPTED task: ``(note, drop_uncertain_objective)`` to dismiss it
    with that note, None to leave it alone. Pure; Core.settle_interrupted journals the result."""
    kind = t.get("kind") or "conversation"
    state = (t.get("recovery") or {}).get("state")
    age = _settle_age_s(t, now)
    if kind == "eval":
        return ("a quality case cut by a restart; the suite runs it again", False)
    if kind == "autonomous":
        if state != "UNCERTAIN":
            return ("an autonomous attempt cut by a restart; the objective makes a fresh attempt", False)
        if age >= SETTLE_UNCERTAIN_S:
            return (f"UNCERTAIN for {int(SETTLE_UNCERTAIN_S // 86400)} days, nobody resumed it; dismissed", True)
        return None
    if kind == "conversation":
        if state == "UNCERTAIN":
            return None
        if age >= SETTLE_CONVERSATION_S:
            return (f"interrupted {int(age // 3600)} h ago; too old to continue safely", False)
        return None
    return None  # an unknown kind is nobody's to dismiss


def _settle_kept_why(t: dict) -> str:
    kind = t.get("kind") or "conversation"
    state = (t.get("recovery") or {}).get("state")
    if kind == "autonomous":
        return "UNCERTAIN: a human decides (uncertain-task objective)"
    if kind == "conversation":
        return "UNCERTAIN: the human's work" if state == "UNCERTAIN" else "young enough for the human to resume"
    return f"kind {kind!r} is not settled at boot"


def _explain(e: Exception) -> str:
    cause = e.__cause__ or e
    text = str(e) if isinstance(e, ToolCrash) else (str(cause) or cause.__class__.__name__)  # a crash names its tool
    if "api_key" in text.lower() or "401" in text or "authentication" in text.lower():
        return "LLM authentication failed. Check api_key in backend/config/config.toml."
    return text[:500]


_core: Optional[Core] = None


def get_core() -> Core:
    global _core
    if _core is None:
        _core = Core()
    return _core
