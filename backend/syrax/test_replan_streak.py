"""Phase 2, replanning: three tool calls in a row that ran and failed (each a different call, so the loop guard never
sees them) get REPLAN_NOTE once in the third observation and a journaled plan.replan; a success resets the count; a
refusal and a call the loop guard answered leave it as it is. The tools are faked: nothing runs."""

import asyncio

from syrax import agent as agent_mod
from syrax.agent import REPLAN_NOTE, SyraxAgent, _succeeded
from syrax.core import _journal_type
from syrax.journal import Event, get_journal
from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, reply, script, server  # noqa: F401

MARK = "Three tool calls in a row failed"
LONG_FAIL = "{'observation': '" + "x" * 900 + "', 'success': False}"  # the flag only at the end, past _succeeded's head


def fake_tools(monkeypatch, results, refuse=()):
    """_call_tool answers from `results` in order; `refuse` names the tools the permission gate turns down."""
    queue = list(results)

    async def fake_call(self, command, name):
        return queue.pop(0)

    orig_permit = SyraxAgent._permit

    async def permit(self, command, decision=None):
        if command.function.name in refuse:
            return "Error: refused: not allowed in this test"
        return await orig_permit(self, command, decision)

    monkeypatch.setattr(SyraxAgent, "_call_tool", fake_call)
    monkeypatch.setattr(SyraxAgent, "_permit", permit)
    return queue


def run_task(script, calls, final="Done."):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    script.queue = list(calls) + [reply(final)]

    async def go():
        tid = await core.submit("fix the thing", said="fix the thing", session_id=None, kind="conversation")
        await core.wait()
        return core.journal.task(tid)

    task = asyncio.run(go())
    texts = [m.content or "" for m in script.seen[-1] if getattr(m, "role", None) == "tool"]
    events = get_journal().events(task["task_id"])
    return task, texts, events


def py(i):
    return call("python_execute", {"code": f"print({i})"}, cid=f"p{i}")


def test_three_failures_in_a_row_get_the_note_once_and_a_plan_replan(script, monkeypatch):
    fake_tools(monkeypatch, ["Error: patch did not apply", LONG_FAIL, "Error: no such file", "Error: still failing"])
    calls = [call("apply_patch", {"patch": "a"}, cid="a1"), py(1),
             call("str_replace_editor", {"command": "view", "path": "/nope"}, cid="e1"), py(2)]
    task, texts, events = run_task(script, calls)
    assert task["status"] == "SUCCESS"
    assert [MARK in t for t in texts] == [False, False, True, False]  # once per streak, on the third
    assert texts[2].startswith("Error: no such file")
    assert texts[2].endswith(REPLAN_NOTE.format(tools="apply_patch, python_execute, str_replace_editor"))
    assert "[SYRAX check, not a new request]" in texts[2]
    replans = [e for e in events if e["type"] == "plan.replan"]
    assert len(replans) == 1
    assert replans[0]["payload"]["streak"] == 3
    assert replans[0]["payload"]["tools"] == ["apply_patch", "python_execute", "str_replace_editor"]
    kinds = [e["type"] for e in events if e["type"].startswith("tool.") and e["type"] != "tool.started"]
    assert kinds == ["tool.failed"] * 4  # the note never turns a failure into a success (LONG_FAIL included)
    final = [e for e in events if e["type"] == "final"][-1]["payload"]["text"]
    assert MARK not in final and "Done." in final


def test_a_success_resets_the_streak(script, monkeypatch):
    fake_tools(monkeypatch, ["Error: 1", "Error: 2", "ok", "Error: 3", "Error: 4", "Error: 5"])
    task, texts, events = run_task(script, [py(i) for i in range(6)])
    assert [MARK in t for t in texts] == [False, False, False, False, False, True]
    assert len([e for e in events if e["type"] == "plan.replan"]) == 1


def test_a_new_streak_gets_the_note_again(script, monkeypatch):
    fake_tools(monkeypatch, ["Error: 1", "Error: 2", "Error: 3", "ok", "Error: 4", "Error: 5", "Error: 6"])
    task, texts, events = run_task(script, [py(i) for i in range(7)])
    assert [MARK in t for t in texts] == [False, False, True, False, False, False, True]
    assert len([e for e in events if e["type"] == "plan.replan"]) == 2


def test_refusals_and_loop_guarded_repeats_neither_count_nor_reset(script, monkeypatch):
    fake_tools(monkeypatch, ["Error: 1", "Error: 2", "Error: 3"], refuse=("desktop",))
    calls = [py(1), py(2), call("desktop", {"action": "screenshot"}, cid="d1"),
             call("python_execute", {"code": "print(2)"}, cid="p2b"),  # the same call as py(2): the loop guard answers
             py(3)]
    task, texts, events = run_task(script, calls)
    assert texts[2].startswith("Error: refused") and MARK not in texts[2]
    assert texts[3].startswith("Not run again") and MARK not in texts[3]
    assert MARK in texts[4] and [MARK in t for t in texts].count(True) == 1
    assert [e["payload"]["tools"] for e in events if e["type"] == "plan.replan"] == [["python_execute"] * 3]


def test_the_note_keeps_a_failure_a_failure_and_journals_as_its_group():
    note = REPLAN_NOTE.format(tools="python_execute")
    assert not _succeeded(LONG_FAIL + note) and not _succeeded("Error: x" + note)
    assert _succeeded("{'observation': 'fine', 'success': True}" + note)
    assert agent_mod.REPLAN_STREAK == 3
    assert _journal_type({"type": "plan", "event": "replan", "streak": 3}) == "plan.replan"
    wire = Event(id=1, ts=0.0, task_id="t", type="plan.replan", seq=1, payload={"event": "replan", "streak": 3}).wire()
    assert wire["type"] == "plan" and wire["event"] == "replan" and wire["streak"] == 3
