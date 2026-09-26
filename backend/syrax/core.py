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
import sqlite3
from dataclasses import dataclass, field
from typing import Awaitable, Callable, List, Optional

from app.logger import logger
from app.schema import Message

from syrax.agent import SyraxAgent
from syrax.brains import get_router
from syrax.journal import Event, Journal, JournalError, get_journal
from syrax.memory import get_memory
from syrax.research import KnowTool, LearnTool, Researcher, ResearchTool
from syrax.selfmodel import SelfInspectTool, SelfModel

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


class Core:
    def __init__(self, journal: Optional[Journal] = None):
        self.journal = journal or get_journal()
        self.agent: Optional[SyraxAgent] = None
        self.current: Optional[Running] = None
        self.observers: List[Observer] = []
        self.state: dict = {"state": "idle"}  # last direct state event
        self.journal.subscribe(self._on_journal_event)
        self.selfmodel = SelfModel(self.journal)
        self.selfmodel.tools_provider = self.tool_names
        self.selfmodel.brains_provider = lambda: get_router().describe()
        self.selfmodel.running_provider = lambda: self.snapshot()["running"]
        from syrax.autonomy import Autonomy  # local import: autonomy depends on the core type

        self.autonomy = Autonomy(self)
        self.researcher = Researcher(self.journal, task_id_provider=self.current_task_id)

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
        for cb in list(self.observers):
            try:
                await cb(event)
            except Exception as e:
                logger.warning(f"observer failed: {e}")

    async def _on_journal_event(self, ev: Event) -> None:
        await self.broadcast(ev.wire())

    # ——— agent ———

    async def ensure_agent(self) -> SyraxAgent:
        if self.agent is None:
            self.agent = await SyraxAgent.create(emit=self.emit)
            self.agent.checkpoint = self._checkpoint
            tools = self.agent.available_tools
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
        return self.agent

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
        if kind in ("tool.completed", "tool.failed"):
            self.current.steps.append(
                {"step": event.get("step"), "tool": event.get("name"), "id": event.get("id"), "ok": bool(event.get("ok"))}
            )
        try:
            await self.journal.record(kind, payload, task_id=self.current.task_id, volatile=volatile)
        except (sqlite3.Error, JournalError) as e:
            # Bookkeeping must never kill a task, but we never pretend it was journaled.
            self.current.unjournaled += 1
            logger.warning(f"journal refused {kind} for {self.current.task_id}: {e}")
            await self.broadcast({**event, "unjournaled": True, "task_id": self.current.task_id})

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
        self, goal: str, said: Optional[str], session_id: Optional[str], kind: str = "conversation"
    ) -> Optional[str]:
        """Start a task. Returns its id, or None when SYRAX is already busy."""
        if self.busy:
            return None
        await self.ensure_agent()
        task_id = await self.journal.start_task(said or goal, session_id=session_id, kind=kind)
        self.current = Running(task_id=task_id, goal=goal, session_id=session_id, kind=kind)
        self.current.task = asyncio.create_task(self._run(goal, said))
        return task_id

    async def wait(self) -> None:
        """Wait for the running task (if any) to finish. Never raises."""
        if self.current is not None and self.current.task is not None:
            await asyncio.gather(self.current.task, return_exceptions=True)

    async def _run(self, request: str, said: Optional[str]) -> None:
        assert self.agent is not None and self.current is not None
        try:
            reply = await self.agent.run(request)
            await self.journal.record("final", {"text": reply}, task_id=self.current.task_id)
            await self._checkpoint("final", verified={"final": True}, next_action=None)
            status = "PARTIAL" if self.agent.step_limit_hit else "SUCCESS"
            await self.journal.record(
                "task.completed", {"status": status, "result": reply}, task_id=self.current.task_id
            )
            if self.current.kind == "conversation":  # autonomous work is not a conversation
                try:
                    get_memory().add_exchange(said or request, reply)
                except Exception as e:
                    logger.warning(f"could not save history: {e}")
        except asyncio.CancelledError:
            self.agent.repair_memory(aborted=True)
            await self._mark("task.cancelled", {"error": "aborted by human"})
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
            self.current = None
            await self.broadcast({"type": "state", "state": "idle"})

    async def cancel(self) -> bool:
        if not self.busy:
            return False
        assert self.current is not None and self.current.task is not None
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
        self.current = Running(
            task_id=task_id,
            goal=task["goal"],
            session_id=session_id,
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
            }
        interrupted = [
            _interrupted_summary(t) for t in self.journal.tasks(limit=10, status="INTERRUPTED")
        ]
        return {
            "state": dict(self.state),
            "running": running,
            "interrupted": interrupted,
            "recent": [_task_summary(t) for t in self.journal.tasks(limit=10)],
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
