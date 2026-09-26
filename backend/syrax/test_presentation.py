"""Presentation engine: decisions come from real events, elements are ephemeral."""

import asyncio
import time

from syrax.journal import Journal
from syrax.presentation import PresentTool, PresentationEngine


def setup(tmp_path):
    j = Journal(tmp_path / "j.db")
    seen = []

    async def emit(e):
        seen.append(e)

    engine = PresentationEngine(j, emit=emit)
    j.subscribe(engine.on_event)
    t = j.start_task_sync("do work")
    return j, engine, t, seen


def kinds(engine):
    return [e["kind"] for e in engine.plan()["elements"]]


async def rec(j, *a, **k):
    return await j.record(*a, **k)


def test_task_lifecycle_drives_the_stage(tmp_path):
    j, engine, t, _ = setup(tmp_path)

    async def go():
        await j._fanout(__import__("syrax.journal", fromlist=["Event"]).Event(0, time.time(), t, "task.started", 1, {"goal": "do work", "kind": "conversation"}))
        assert kinds(engine) == ["status"] and engine.plan()["elements"][0]["data"]["text"] == "do work"
        await rec(j, "tool.started", {"id": "c", "name": "python_execute", "args": {"code": "print(1)"}, "step": 1}, task_id=t)
        assert kinds(engine) == ["code", "status"]  # code outranks the ambient status
        code = engine.plan()["elements"][0]
        assert code["data"]["code"] == "print(1)" and code["slot"] == "tool" and code["ttl_s"] == 120
        await rec(j, "tool.completed", {"id": "c", "name": "python_execute", "ok": True, "output": "1\n"}, task_id=t)
        assert kinds(engine) == ["terminal", "status"]  # replaced the code element in the same slot
        term = engine.plan()["elements"][0]
        assert term["replaces"] == code["presentation_id"] and term["data"]["text"] == "1\n"
        await rec(j, "final", {"text": "done"}, task_id=t)
        assert sorted(kinds(engine)) == ["card", "status", "terminal"]
        await rec(j, "task.completed", {"status": "SUCCESS"}, task_id=t)
        assert kinds(engine) == ["card"]  # status dismissed by task end, tool slot cleared, reply lingers
        plan = engine.plan()
        assert plan["minimal"] is False
        engine.active[plan["elements"][0]["presentation_id"]]["created"] -= 1000
        assert await engine.expire() == 1 and engine.plan() == {"elements": [], "minimal": True}

    asyncio.run(go())
    shown = [e for e in j.recent_events() if e["type"].startswith("presentation.")]
    assert all(e["task_id"] is None and e["payload"]["task_id"] == t for e in shown)  # task-less, correlated by payload
    assert "presentation.created" not in [e["type"] for e in j.events(t)]  # the task's own history stays clean
    kinds_journaled = [e["type"] for e in shown]
    assert kinds_journaled.count("presentation.created") == 4 and kinds_journaled.count("presentation.dismissed") == 3  # a slot replacement is recorded on the new element (replaces), not as a dismissal
    dismissed = [e["payload"]["reason"] for e in shown if e["type"] == "presentation.dismissed"]
    assert "dismissed by task.completed" in dismissed and "task ended" in dismissed and "expired" in dismissed


def test_failures_asks_and_edits(tmp_path):
    j, engine, t, _ = setup(tmp_path)

    async def go():
        await rec(j, "tool.started", {"id": "e", "name": "str_replace_editor", "args": {"command": "create", "path": "/x/y.py", "file_text": "x = 1"}}, task_id=t)
        el = engine.plan()["elements"][0]
        assert el["kind"] == "code" and el["data"]["path"] == "/x/y.py" and el["data"]["code"] == "x = 1"
        await rec(j, "tool.failed", {"id": "e", "name": "str_replace_editor", "ok": False, "output": "Error: nope"}, task_id=t)
        alert = [e for e in engine.plan()["elements"] if e["kind"] == "notification"][0]
        assert alert["attention"] == "focus" and alert["data"]["level"] == "error" and "nope" in alert["data"]["text"]
        await rec(j, "ask", {"question": "which file?"}, task_id=t)
        q = [e for e in engine.plan()["elements"] if e["kind"] == "notification"][0]
        assert q["data"]["level"] == "question" and q["replaces"] == alert["presentation_id"] and "answer" in q["dismiss_on"]
        await rec(j, "answer", {"text": "that one"}, task_id=t)
        assert not [e for e in engine.plan()["elements"] if e["kind"] == "notification"]
        await rec(j, "research.completed", {"question": "q?", "sources": 2, "stored": 2}, task_id=t)
        assert [e for e in engine.plan()["elements"] if e["kind"] == "list"][0]["data"]["stored"] == 2
        await engine.on_direct({"type": "error", "message": "brain melted"})
        assert any(e["kind"] == "notification" and "brain melted" in e["data"]["text"] for e in engine.plan()["elements"])
        await engine.on_direct({"type": "state", "state": "idle"})  # ignored

    asyncio.run(go())


def test_journal_outage_still_reaches_observers(tmp_path):
    j, engine, t, seen = setup(tmp_path)
    j._db.close()

    async def go():
        await engine.show("card", "x", {"text": "hi"})

    asyncio.run(go())
    assert seen and seen[0]["type"] == "presentation" and seen[0]["event"] == "created" and seen[0]["unjournaled"] is True


def test_present_tool_validates_and_clears(tmp_path):
    j, engine, t, _ = setup(tmp_path)
    tool = PresentTool()
    assert asyncio.run(tool.execute(kind="card", text="x")).error
    tool.engine = engine
    tool.task_id_provider = lambda: t
    assert asyncio.run(tool.execute(kind="card")).error
    assert asyncio.run(tool.execute(kind="table", rows="nope")).error
    assert asyncio.run(tool.execute(kind="list")).error
    assert asyncio.run(tool.execute(kind="hologram", text="x")).error
    out = asyncio.run(tool.execute(kind="table", title="Results", rows=[["name", "ms"], ["a", 1]], ttl_s=1))
    assert not out.error and "shown table" in out.output
    el = engine.plan()["elements"][0]
    assert el["source"] == "model" and el["data"]["rows"] == [["name", "ms"], ["a", "1"]] and el["ttl_s"] == 5.0 and el["task_id"] == t
    out = asyncio.run(tool.execute(kind="code", text="print(1)", language="python"))
    assert "shown code" in out.output and len(engine.plan()["elements"]) == 1  # same slot: replaced
    asyncio.run(tool.execute(kind="list", items=["a", "b"], attention="focus"))
    assert engine.plan()["elements"][0]["attention"] == "focus"
    out = asyncio.run(tool.execute(kind="none"))
    assert "cleared (1" in out.output and engine.plan()["minimal"]
    assert asyncio.run(tool.execute(kind="card", text="x", attention="loud")).error


def test_human_feedback_teaches_the_engine_to_be_quiet(tmp_path):
    j, engine, t, _ = setup(tmp_path)

    async def go():
        assert not await engine.feedback("nope")
        for i in range(5):
            el = await engine.show("terminal", "output", {"text": "x"}, ttl_s=90, slot="tool")
            el["created"] -= 1  # dismissed one second after being shown
            assert await engine.feedback(el["presentation_id"])
            assert el["presentation_id"] not in engine.active
        prefs = engine.preferences(refresh=True)
        assert prefs["terminal"]["quiet"] and prefs["terminal"]["human_dismissed"] == 5 and prefs["terminal"]["median_dismiss_after_s"] < 5
        quiet = await engine.show("terminal", "output", {"text": "y"}, ttl_s=90, slot="tool")
        assert quiet["ttl_s"] == 20.0 and quiet["attention"] == "ambient"  # evidence changed the decision
        chosen = await engine.show("terminal", "output", {"text": "z"}, ttl_s=90, slot="model", source="model")
        assert chosen["ttl_s"] == 90  # SYRAX's explicit choices are not overridden
        card = await engine.show("card", "reply", {"text": "r"}, ttl_s=90, slot="reply")
        assert card["ttl_s"] == 90  # only the kind with evidence changes

    asyncio.run(go())
    fb = [e for e in j.recent_events(500) if e["type"] == "presentation.feedback"]
    assert len(fb) == 5 and all(e["payload"]["kind"] == "terminal" and e["payload"]["after_s"] >= 1 for e in fb)
    stats = j.presentation_stats()
    assert stats["terminal"]["shown"] == 7 and stats["terminal"]["human_dismissed"] == 5
