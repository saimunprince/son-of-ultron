"""Audit follow-up 2026-10-26 (docs/AUDIT_2026-10-25.md, open items): Core.resume continued an INTERRUPTED
task with none of the preparation _begin gives a new one, so the previous task's step budget (a release
objective's 30) leaked into it, no brain was routed for it and the UI saw no phase; and the UI offered that
RESUME on SYRAX's own work too (an autonomous attempt, a quality case), which the boot policy dismisses.
Now a conversation resumes through the preparation a new task gets (Core._prepare, shared with _begin), and
own work is never resumed: the resume answers with the note the UI shows and dismisses the task the way the
boot policy would. The UNCERTAIN/force rule and the intent note stay as they were."""

import asyncio

from syrax import core as core_mod
from syrax.core import OWN_WORK_NOT_RESUMED
from syrax.test_bridge import (  # noqa: F401
    ORIGIN, TestClient, boot, drain_until_idle, get_journal, recv_until, reply, script, server,
)
from syrax.test_resume_uncertain import uncertain_task

DEFAULT_STEPS = 20  # SyraxAgent's own budget (test_core_steps pins it)
SHOT = {"id": "e1", "name": "desktop", "args": {"action": "screenshot"}, "step": 2}
APPEND = {"id": "e1", "name": "python_execute", "args": {"code": "open('r.txt', 'a').write('x')"}, "step": 2}
ATTEMPT = "an autonomous attempt is not resumed; it is dismissed and the objective makes a fresh attempt"
CASE = "a quality case is run again by the suite, never resumed"


def interrupted(goal: str, kind: str = "conversation", op: dict = SHOT, state: str = "RESUMABLE", context=None) -> str:
    """A previous process died mid-operation; recovery classified the task. With ``context`` it had checkpointed."""
    j = get_journal()
    t = j.start_task_sync(goal, kind=kind)
    j.record_sync("think", {"step": 1, "content": "working"}, task_id=t)
    if context is not None:
        j.checkpoint_sync(t, "observed:python_execute", completed_steps=[{"step": 1, "tool": "python_execute", "id": "c1", "ok": True}],
                          verified={"ok": True}, context=context, evidence_state="SUCCESS")
    j.record_sync("tool.started", op, task_id=t)
    j.record_sync("task.interrupted", {
        "error": "restart",
        "recovery": {"state": state, "operation_state": "UNCERTAIN" if state == "UNCERTAIN" else "NOT_STARTED", "operation": op},
    }, task_id=t)
    return t


def spy_route(monkeypatch) -> list:
    """Every _route call, as (text, task_id, release); the real routing still runs."""
    calls = []
    orig = core_mod.Core._route

    async def route(self, text, task_id, release=False):
        calls.append((text, task_id, release))
        return await orig(self, text, task_id, release=release)

    monkeypatch.setattr(core_mod.Core, "_route", route)
    return calls


def model_view(core, text):
    """A scripted brain reply that first notes what the agent looked like when the model was asked."""
    seen = {}

    async def answer():
        seen.update(max_steps=core.agent.max_steps, task_kind=core.agent.task_kind, task_goal=core.agent.task_goal,
                    phase=core.current.phase)
        return reply(text)

    return seen, answer


def resume_and_wait(core, task_id, **kw):
    async def go():
        problem = await core.resume(task_id, session_id=None, **kw)
        await core.wait()
        return problem

    return asyncio.run(go())


def contents(messages) -> list:
    return [getattr(m, "content", "") or "" for m in messages]


# ——— a conversation resumes through the preparation a new task gets ———


def test_a_resumed_conversation_gets_the_preparation_a_new_task_gets(script, monkeypatch):
    routed = spy_route(monkeypatch)
    t = interrupted("write greeting file", context=[
        {"role": "user", "content": "write greeting file"},
        {"role": "assistant", "content": "ok, writing it now"},
    ])
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        hello = boot(ws)
        assert [i["recovery_state"] for i in hello["interrupted"]] == ["RESUMABLE"]
    core = core_mod.get_core()
    core.agent.max_steps = 30  # a release objective's budget, left behind by the previous task
    core.agent.task_kind, core.agent.task_goal = "autonomous", "the previous brief"
    seen, answer = model_view(core, "Greeting file is there. Done.")
    script.queue = [answer]
    told = []

    async def observe(e):
        told.append(e)

    core.subscribe(observe)
    try:
        assert resume_and_wait(core, t) is None
    finally:
        core.unsubscribe(observe)

    # the agent was prepared as for a new task: a fresh budget, the kind, the human's words, the first phase
    assert seen == {"max_steps": DEFAULT_STEPS, "task_kind": "conversation", "task_goal": "write greeting file", "phase": "understand"}
    assert core.agent.max_steps == DEFAULT_STEPS == type(core.agent).model_fields["max_steps"].default
    assert routed == [("write greeting file", t, False)]
    phases = [e for e in told if e.get("type") == "phase"]
    assert phases[0] == {"type": "phase", "event": "changed", "phase": "understand", "from": None, "task_id": t}
    # the human's context came back from the checkpoint, with the resume note and the continuation
    asked = contents(script.seen[-1])
    assert "ok, writing it now" in asked
    assert any("RESUMED AFTER INTERRUPTION" in c and "NOT_STARTED" in c for c in asked)
    assert any("Continue the interrupted task: write greeting file" in c for c in asked)
    assert "ok, writing it now" in contents(core.agent.memory.messages)  # still the agent's conversation afterwards
    j = get_journal()
    assert j.task(t)["status"] == "SUCCESS"
    kinds = [e["type"] for e in j.events(t)]
    assert kinds[-5:] == ["recovery.resumed", "think", "final", "checkpoint.created", "task.completed"]  # the phase is told, not journaled


def test_a_forced_resume_of_an_uncertain_conversation_runs_as_before_through_the_same_preparation(script, monkeypatch):
    routed = spy_route(monkeypatch)
    t = uncertain_task()
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    core.agent.max_steps = 30
    seen, answer = model_view(core, "The report has 37 lines; the append ran once.")
    script.queue = [answer]

    problem = resume_and_wait(core, t)
    assert problem.startswith(f"task {t}'s last operation is UNCERTAIN (python_execute") and "force" in problem
    assert routed == [] and script.seen == [] and get_journal().task(t)["status"] == "INTERRUPTED"

    assert resume_and_wait(core, t, force=True, note="confirmed in the UI") is None
    assert seen == {"max_steps": DEFAULT_STEPS, "task_kind": "conversation", "task_goal": "count the lines of the report", "phase": "understand"}
    assert routed == [("count the lines of the report", t, False)]
    j = get_journal()
    assert j.task(t)["status"] == "SUCCESS"
    kinds = [e["type"] for e in j.events(t)]
    assert kinds.index("task.resume_forced") < kinds.index("recovery.resumed") < kinds.index("task.completed")
    assert any("RESUMED AFTER INTERRUPTION" in c and "UNCERTAIN" in c for c in contents(script.seen[-1]))


# ——— SYRAX's own work is never resumed: it is dismissed as the boot policy would ———


def send_resume(ws, task_id, **kw) -> list:
    """The RESUME button's message, then a ping: the notices the resume produced come before the pong."""
    ws.send_json({"type": "resume", "task_id": task_id, **kw})
    ws.send_json({"type": "ping"})
    _, seen = recv_until(ws, "pong")
    assert not any(e["type"] == "recovery" and e.get("event") == "resumed" for e in seen), seen
    return [e["text"] for e in seen if e["type"] == "notice"]


def test_resume_of_an_autonomous_attempt_dismisses_it_and_reopens_its_objective(script):
    assert OWN_WORK_NOT_RESUMED["autonomous"] == ATTEMPT
    goal = "Brain latency: three steps, one release."
    t = interrupted(goal, kind="autonomous")
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        hello = boot(ws)
        assert [i["task_id"] for i in hello["interrupted"]] == [t]
        j = get_journal()
        # the core exists now (Autonomy.recover_active ran at its birth): the cycle's ACTIVE marks come after that
        by_goal = j.add_objective_sync(goal, "test", 2, "human", {"kind": "change_released"})
        by_task = j.add_objective_sync("another goal; an earlier attempt of it was this task", "test", 2, "human")
        other = j.add_objective_sync("unrelated work", "test", 3, "human")
        j.update_objective_sync(by_goal["id"], status="ACTIVE", note="cycle picked this objective")
        j.update_objective_sync(by_task["id"], status="ACTIVE", last_task_id=t, note="cycle picked this objective")
        j.update_objective_sync(other["id"], status="ACTIVE", note="cycle picked this objective")

        assert send_resume(ws, t) == [ATTEMPT]

        ws.send_json({"type": "history", "limit": 5})  # the session is still alive and serves
        recv_until(ws, "history")
    core = core_mod.get_core()
    assert not core.busy and script.seen == []  # nothing ran, the brain was never asked
    row = j.task(t)
    assert row["status"] == "CANCELLED" and row["error"] == ATTEMPT
    last = j.events(t)[-1]
    assert last["type"] == "task.cancelled" and last["payload"]["error"] == ATTEMPT
    assert "recovery.resumed" not in [e["type"] for e in j.events(t)]
    for o in (by_goal, by_task):
        assert j.objective(o["id"])["status"] == "OPEN"
        ev = [e for e in j.recent_events(limit=50) if e["type"] == "objective.updated" and e["payload"]["objective_id"] == o["id"]][-1]
        assert ev["payload"]["note"] == f"task {t} dismissed on resume: {ATTEMPT}"
    assert j.objective(other["id"])["status"] == "ACTIVE"  # not this task's
    assert core.snapshot()["interrupted"] == []  # gone from the next hello too


def test_resume_of_a_quality_case_dismisses_it_for_the_suite_to_run_again(script):
    assert OWN_WORK_NOT_RESUMED["eval"] == CASE
    t = interrupted("eval: count the lines", kind="eval")
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        assert send_resume(ws, t) == [CASE]
    j = get_journal()
    row = j.task(t)
    assert row["status"] == "CANCELLED" and row["error"] == CASE
    assert j.events(t)[-1]["type"] == "task.cancelled" and j.events(t)[-1]["payload"]["error"] == CASE
    assert script.seen == [] and not core_mod.get_core().busy


def test_an_uncertain_attempt_still_waits_for_the_humans_word_then_is_dismissed_with_its_question(script):
    t = interrupted("objective Z", kind="autonomous", op=APPEND, state="UNCERTAIN")
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        j = get_journal()
        ask = j.add_objective_sync(f"Interrupted task {t} has an UNCERTAIN in-flight operation; a human must decide.",
                                  "never repeat an operation whose completion is unknown", 2, "selfmodel",
                                  {"kind": "human"}, key=f"uncertain-task:{t}", status="BLOCKED")

        notices = send_resume(ws, t)  # the UNCERTAIN/force rule first, and it says what force will do
        assert len(notices) == 1, notices
        assert notices[0].startswith(f"task {t}'s last operation is UNCERTAIN (python_execute") and "force" in notices[0]
        assert ATTEMPT in notices[0]
        assert j.task(t)["status"] == "INTERRUPTED" and j.objective(ask["id"])["status"] == "BLOCKED"

        assert send_resume(ws, t, force=True, note="confirmed in the UI") == [ATTEMPT]
    row = j.task(t)
    assert row["status"] == "CANCELLED" and row["error"] == ATTEMPT
    kinds = [e["type"] for e in j.events(t)]
    assert "task.resume_forced" not in kinds and "recovery.resumed" not in kinds  # it was never resumed
    last = j.events(t)[-1]
    assert last["type"] == "task.cancelled" and last["payload"]["error"] == ATTEMPT and last["payload"]["note"] == "confirmed in the UI"
    assert j.objective(ask["id"])["status"] == "DROPPED"  # the human decided: the question is answered
    drop = [e for e in j.recent_events(limit=50) if e["type"] == "objective.dropped"][-1]
    assert drop["payload"]["objective_id"] == ask["id"] and drop["payload"]["note"] == f"task {t} dismissed on resume: {ATTEMPT}"
    assert script.seen == []


def test_auto_resume_leaves_own_work_to_the_boot_policy(script, monkeypatch):
    monkeypatch.setenv("SYRAX_AUTO_RESUME", "1")
    a = interrupted("objective A", kind="autonomous")
    e = interrupted("eval: a case", kind="eval")
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    j = get_journal()

    async def lifespan_order():  # the server lifespan: auto_resume first, then the boot policy
        started = await core.auto_resume()
        untouched = {t: j.task(t)["status"] for t in (a, e)}
        return started, untouched, await core.settle_interrupted()

    started, untouched, settled = asyncio.run(lifespan_order())
    # auto-resume neither resumed nor dismissed them; the boot policy did, with its own notes
    assert started == [] and untouched == {a: "INTERRUPTED", e: "INTERRUPTED"} and not core.busy
    assert {d["task_id"]: d["note"] for d in settled["dismissed"]} == {
        a: "an autonomous attempt cut by a restart; the objective makes a fresh attempt",
        e: "a quality case cut by a restart; the suite runs it again",
    }
    for tid in (a, e):
        assert j.task(tid)["status"] == "CANCELLED"
        assert "recovery.resumed" not in [ev["type"] for ev in j.events(tid)]
    assert script.seen == []
