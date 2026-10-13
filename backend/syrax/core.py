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
import sqlite3
from dataclasses import dataclass, field
from typing import Awaitable, Callable, List, Optional

from app.logger import logger
from app.schema import Message

from syrax.agent import SyraxAgent
from syrax.brains import get_router
from syrax import phases
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
    if t == "claim" and event.get("event") == "rejected":
        return "claim.rejected"
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


def _is_release(goal: str) -> bool:
    """An autonomous brief for an objective that closes only on a landed commit."""
    from syrax.autonomy import RELEASE_MARK

    return RELEASE_MARK in (goal or "")


class Core:
    def __init__(self, journal: Optional[Journal] = None):
        self.journal = journal or get_journal()
        self.agent: Optional[SyraxAgent] = None
        self.current: Optional[Running] = None
        # the human's conversation, kept aside while SYRAX does its own work
        self._human_context: Optional[list] = None
        self._submit_lock = asyncio.Lock()
        self._agent_lock = asyncio.Lock()
        self.observers: List[Observer] = []
        self.state: dict = {"state": "idle"}  # last direct state event
        self._last_tool_args: dict = {}
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
        return self.current is not None and self.current.task is not None and not self.current.task.done()

    async def emit(self, event: dict) -> None:
        """The agent's single output port: journal what matters, pass the rest."""
        kind = _journal_type(event)
        if kind is None or self.current is None:
            await self.broadcast(event)
            return
        payload = {k: v for k, v in event.items() if k not in ("type", "image")}
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
        """Terminal marks: best effort, logged, never raised (we are in except paths)."""
        if self.current is None:
            return
        try:
            await self.journal.record(kind, payload, task_id=self.current.task_id)
        except (sqlite3.Error, JournalError) as e:
            logger.warning(f"journal {kind} failed for {self.current.task_id}: {e}")

    # ——— commands ———

    async def submit(
        self, goal: str, said: Optional[str], session_id: Optional[str], kind: str = "conversation",
        max_steps: Optional[int] = None,
    ) -> Optional[str]:
        """Start a task. Returns its id, or None when SYRAX is already busy
        (also when another submit got there first while this one waited)."""
        async with self._submit_lock:
            if self.busy:
                return None
            await self.ensure_agent()
            await asyncio.to_thread(self.devloop.begin_task)  # a task owns only the changes it makes
            task_id = await self.journal.start_task(said or goal, session_id=session_id, kind=kind)
            if kind == "autonomous" and os.getenv("SYRAX_ISOLATE", "0") == "1":
                # M1, isolated evolution: SYRAX's own work happens in a worktree, never in the running tree
                try:
                    wt = await asyncio.to_thread(self.devloop.isolate, task_id)
                    from syrax import editor as _editor

                    _editor.ROOT_MAP = (self.devloop.live_root, wt)
                    goal = goal + ISOLATION_NOTE.format(worktree=wt, live=self.devloop.live_root)
                    await self.journal.record("isolation.started", {"worktree": str(wt)}, task_id=task_id)
                except Exception as e:
                    logger.warning(f"could not isolate task {task_id}: {e}")
                    await self.journal.record("isolation.failed", {"error": str(e)[:300]}, task_id=task_id)
            await self._route(said or goal, task_id, release=kind == "autonomous" and _is_release(goal))
            self.current = Running(task_id=task_id, goal=goal, session_id=session_id, kind=kind, phase="understand")
            await self._record_phase({"phase": "understand", "from": None})
            if self.agent is not None:  # permissions: the kind and the human's own words (not the brief)
                self.agent.task_kind = kind
                self.agent.task_goal = said or goal
                # a budget is per task: a release objective's 30 steps never leak into the next task
                fields = getattr(type(self.agent), "model_fields", {})
                if "max_steps" in fields:
                    self.agent.max_steps = max_steps or fields["max_steps"].default
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
            self.current.task = asyncio.create_task(self._run(goal, said))
            return task_id

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
            await self.journal.record(
                "task.completed", {"status": status, "result": reply}, task_id=self.current.task_id
            )
            # conversation history now comes from the journal (tasks of kind
            # "conversation"); history.jsonl is no longer written.
        except asyncio.CancelledError:
            self.agent.repair_memory(aborted=True)
            await self._mark("task.cancelled", {"error": self.current.cancel_reason})
            await self.broadcast({"type": "notice", "text": "Task aborted."})
            raise
        except (sqlite3.Error, JournalError) as e:
            # The work may have finished, but we cannot prove it: say so, never claim success.
            logger.exception("SYRAX journal failure during task")
            self.agent.repair_memory()
            await self._mark("task.failed", {"error": f"journal unavailable: {e}"})
            await self.broadcast({"type": "error", "message": f"Journal unavailable: {str(e)[:200]}"})
        except Exception as e:
            logger.exception("SYRAX task failed")
            self.agent.repair_memory()
            await self._mark("task.failed", {"error": _explain(e)})
            await self.broadcast({"type": "error", "message": _explain(e)})
        finally:
            await self._clean_repo_after_task()
            self.current = None
            await self.broadcast({"type": "state", "state": "idle"})

    async def _clean_repo_after_task(self) -> None:
        """Autonomous work may edit SYRAX's own repository, but only `release`
        (gate → commit) may make that permanent. If such a task ends with
        uncommitted edits of its own — step limit, failure, cancel — restore
        those files so a restart can never load half-finished code. Files that
        were already modified before the task (a human's work) and human
        conversations are left alone."""
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

            _editor.ROOT_MAP = None
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
        if not self.busy:
            return False
        assert self.current is not None and self.current.task is not None
        self.current.cancel_reason = reason
        self.current.task.cancel()
        return True

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
        if self.busy:
            assert self.current is not None and self.current.task is not None
            self.current.task.cancel()
            await asyncio.gather(self.current.task, return_exceptions=True)
        if self.agent:
            self.agent.reset_conversation()
        self._human_context = None

    async def resume(self, task_id: str, session_id: Optional[str]) -> Optional[str]:
        """Continue an INTERRUPTED task from its last checkpoint. Returns an
        error string, or None when the resume started."""
        if self.busy:
            return "Already executing. Stop it first."
        try:
            ctx = self.journal.resume_context(task_id)
        except JournalError as e:
            return str(e)
        agent = await self.ensure_agent()
        task, cp, recovery = ctx["task"], ctx["checkpoint"], ctx["recovery"]
        if cp and cp.get("context"):
            agent.import_context(cp["context"])
        agent.repair_memory()
        op = recovery.get("operation") or {}
        agent.memory.add_message(
            Message.system_message(
                RESUME_NOTE.format(
                    step=task.get("current_step"),
                    stage=task.get("stage"),
                    op=(f"{op.get('name')} {op.get('args')}" if op else "none"),
                    op_state=recovery.get("operation_state", "UNKNOWN"),
                )
            )
        )
        await self.journal.mark_resumed(task_id, session_id)
        await asyncio.to_thread(self.devloop.begin_task)
        kind = task.get("kind") or "conversation"
        agent.task_kind = kind
        agent.task_goal = task["goal"]
        self.current = Running(
            task_id=task_id,
            goal=task["goal"],
            session_id=session_id,
            kind=kind,
            steps=list((cp or {}).get("completed_steps") or []),
        )
        request = f"Continue the interrupted task: {task['goal']}"
        self.current.task = asyncio.create_task(self._run(request, None))
        return None

    async def auto_resume(self) -> List[str]:
        """Boot-time resume of RESUMABLE tasks, only when SYRAX_AUTO_RESUME=1.
        UNCERTAIN operations are never resumed without a human."""
        if os.getenv("SYRAX_AUTO_RESUME", "0") != "1":
            return []
        started: List[str] = []
        for t in self.journal.tasks(limit=50, status="INTERRUPTED"):
            rec = t.get("recovery") or {}
            if rec.get("state") != "RESUMABLE" or self.busy:
                continue
            if await self.resume(t["task_id"], None) is None:
                started.append(t["task_id"])
        return started

    # ——— snapshot for (re)connecting observers ———

    def snapshot(self) -> dict:
        running = None
        if self.busy and self.current is not None:
            row = self.journal.task(self.current.task_id) or {}
            running = {
                "task_id": self.current.task_id,
                "goal": self.current.goal,
                "stage": row.get("stage"),
                "step": row.get("current_step", 0),
                "status": row.get("status"),
                "phase": self.current.phase,
            }
        interrupted = [
            _interrupted_summary(t) for t in self.journal.tasks(limit=10, status="INTERRUPTED")
        ]
        return {
            "state": dict(self.state),
            "running": running,
            "interrupted": interrupted,
            "recent": [_task_summary(t) for t in self.journal.tasks(limit=10)],
            "presentation": self.presentation.plan(),
        }

    async def shutdown(self) -> None:
        await self.autonomy.stop()
        if self.busy:
            assert self.current is not None and self.current.task is not None
            self.current.task.cancel()
            await asyncio.gather(self.current.task, return_exceptions=True)
        if self.agent is not None:
            await self.agent.shutdown()
            self.agent = None
        self.journal.unsubscribe(self._on_journal_event)
        self.journal.unsubscribe(self.presentation.on_event)


async def _cross_review(info: dict, summary: str, authors: List[str]) -> dict:
    if os.getenv("SYRAX_REVIEW", "1") == "0":
        return {"skipped": "SYRAX_REVIEW=0"}
    from syrax.brains import get_router
    from syrax.review import review

    return await review(get_router(), info, summary, authors)


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
        "when": t.get("updated"),
    }


def _explain(e: Exception) -> str:
    cause = e.__cause__ or e
    text = str(cause) or cause.__class__.__name__
    if "api_key" in text.lower() or "401" in text or "authentication" in text.lower():
        return "LLM authentication failed. Check api_key in backend/config/config.toml."
    return text[:500]


_core: Optional[Core] = None


def get_core() -> Core:
    global _core
    if _core is None:
        _core = Core()
    return _core
