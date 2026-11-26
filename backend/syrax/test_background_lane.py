"""The background lane (background.py; idea from Mark-LVII, 2026-11-26): long read-only work beside the chat.

Confinement is judged by permissions.decide (kind "background"), not by the tool list; the budget ends in a
write-up with no tools; cancel, steer, finish, the emergency stop and a brain outage behave as the module says;
the report is written and journaled; and the chat answers while a background task runs.
"""

import asyncio
import os

import pytest

from syrax import background as bg
from syrax import estop
from syrax import permissions as P
from syrax.brains import BrainRouter, BrainError
from syrax.journal import get_journal
from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, reply, script, server  # noqa: F401


@pytest.fixture
def root(tmp_path, monkeypatch):
    r = tmp_path / "background"
    monkeypatch.setattr(P, "BACKGROUND_ROOT", r)
    return r


@pytest.fixture
def tools_seen(script, monkeypatch):
    """The `tools` each brain call offered (None: the write-up call); `.system` the system messages it sent."""
    seen = Seen()
    fake = BrainRouter.ask_tool

    async def rec(self, messages, **kw):
        seen.append(kw.get("tools"))
        seen.system.append(kw.get("system_msgs"))
        return await fake(self, messages, **kw)

    monkeypatch.setattr(BrainRouter, "ask_tool", rec)
    return seen


class Seen(list):
    def __init__(self):
        super().__init__()
        self.system = []


class Notes:
    def __init__(self):
        self.events = []

    async def __call__(self, event):
        self.events.append(event)

    def notices(self):
        return [e["text"] for e in self.events if e.get("type") == "notice"]


def lane():
    notes = Notes()
    return bg.BackgroundLane(get_journal(), notes), notes


def kinds(bid):
    return [e["type"] for e in get_journal().recent_events(500) if (e.get("payload") or {}).get("bg_id") == bid]


def payloads(bid, kind):
    return [e["payload"] for e in get_journal().recent_events(500) if e["type"] == kind and e["payload"].get("bg_id") == bid]


def gate():
    """A brain reply that waits until the test lets it go: (item, entered, release)."""
    entered, release = asyncio.Event(), asyncio.Event()

    def item(msg):
        async def go():
            entered.set()
            await release.wait()
            return msg
        return go
    return item, entered, release


# ——— the permission layer ———

def test_the_background_kind_refuses_memory_desktop_phone_browser_and_code(root):
    folder = root / "bg-1"
    folder.mkdir(parents=True)

    def verdict(name, args):
        return P.decide(P.classify(name, args), P.BACKGROUND_KIND, "research quantum batteries", write_root=folder)

    for name, args in [("remember", {"fact": "x"}), ("recall", {"query": "x"}), ("forget", {"id": 1})]:
        v = verdict(name, args)
        assert v.action == "refuse" and "memory" in v.reason, (name, v)
    for name, args in [("desktop", {"action": "screenshot"}), ("desktop", {"action": "phone", "value": "status"}),
                       ("browser_navigate", {"url": "https://example.com"}), ("python_execute", {"code": "print(1)"}),
                       ("str_replace_editor", {"command": "create", "path": str(folder / "a.md"), "file_text": "x"}),
                       ("journal_query", {"sql": "select 1"}), ("self_inspect", {}), ("learn", {"claim": "x", "sources": []}),
                       ("background", {"action": "start", "instruction": "x"}), ("some_mcp_tool", {})]:
        v = verdict(name, args)
        assert v.action == "refuse", (name, v)
    for name, args in [("research", {"question": "q"}), ("know", {"query": "q"}), ("github_search", {"query": "q"}),
                       ("background_write", {"path": "notes.md", "content": "x"}), ("background_read", {"path": "notes.md"})]:
        assert verdict(name, args).action == "allow", name


def test_background_writes_stay_in_their_own_folder(root, tmp_path):
    folder = root / "bg-1"
    folder.mkdir(parents=True)
    (root / "bg-2").mkdir()
    os.symlink(tmp_path, folder / "out")

    def write(path, write_root=folder):
        return P.decide(P.classify("background_write", {"path": path, "content": "x"}), P.BACKGROUND_KIND, "", write_root=write_root)

    assert write("notes/a.md").action == "allow"
    assert write(str(folder / "b.md")).action == "allow"
    for bad in ("../bg-2/x.md", str(root / "bg-2" / "x.md"), str(tmp_path / "x.md"), "out/x.md", "/etc/passwd", ""):
        assert write(bad).action == "refuse", bad
    assert write("a.md", write_root=None).action == "refuse"
    assert write("a.md", write_root=tmp_path).action == "refuse"  # a root outside BACKGROUND_ROOT is no folder at all
    assert P.decide(P.classify("background_read", {"path": "../bg-2/x.md"}), P.BACKGROUND_KIND, "", write_root=folder).action == "refuse"


def test_own_work_never_starts_background_work():
    d = P.classify("background", {"action": "start", "instruction": "x"})
    for kind in ("autonomous", "eval"):
        assert P.decide(d, kind, "research x in the background").action == "refuse"
    assert P.decide(d, "conversation", "research x in the background").action == "allow"


# ——— the lane ———

def test_refused_calls_and_the_report(tools_seen, script, root):
    script.queue = [
        call("desktop", {"action": "screenshot"}, cid="c1"),
        call("remember", {"fact": "the owner's password"}, cid="c2"),
        call("python_execute", {"code": "print(open('/etc/hosts').read())"}, cid="c3"),
        call("background_write", {"path": "notes.md", "content": "first finding"}, cid="c4"),
        reply("# Batteries\n\nSolid-state cells are close. Source: https://example.com/a"),
    ]
    ln, notes = lane()

    async def go():
        t = await ln.start("research solid-state batteries", minutes=5, steps=10)
        await t.task
        return t
    t = asyncio.run(go())
    assert t.state == "done"
    tool_texts = [m.content for m in script.seen[-1] if getattr(m, "role", None) == "tool"]
    assert [x.startswith("REFUSED") for x in tool_texts] == [True, True, True, False]
    assert (t.folder / "notes.md").read_text(encoding="utf-8") == "first finding"
    report = (t.folder / "report.md").read_text(encoding="utf-8")
    assert "Solid-state cells are close" in report and "Status: SUCCESS" in report
    assert [p["tool"] for p in payloads(t.id, "background.refused")] == ["desktop", "remember", "python_execute"]
    done = payloads(t.id, "background.completed")[0]
    assert done["status"] == "SUCCESS" and done["report"] == str(t.folder / "report.md") and done["refused"] == 3
    assert any(f"Background task {t.id} done: Batteries" in n for n in notes.notices())
    system = " ".join(m.content for m in tools_seen.system[-1])
    assert "no memory of the human" in system  # the lane's own prompt: no persona, no remembered facts
    from syrax import prompt
    assert prompt.SYRAX_PERSONA[:80] not in system


def test_the_budget_ends_in_a_write_up_without_tools(tools_seen, script, root):
    script.queue = [call("know", {"query": "a"}, cid="k1"), call("know", {"query": "b"}, cid="k2"), reply("Report: little known.")]
    ln, _ = lane()

    async def go():
        t = await ln.start("research a thing", steps=3)
        await t.task
        return t
    t = asyncio.run(go())
    assert tools_seen[0] and tools_seen[1] and tools_seen[2] is None
    assert "[BUDGET] This is your last step (3 steps)" in script.seen[-1][-1].content
    assert payloads(t.id, "background.completed")[0]["status"] == "PARTIAL"
    assert "Report: little known." in (t.folder / "report.md").read_text(encoding="utf-8")


def test_the_time_budget_also_ends_it(tools_seen, script, root, monkeypatch):
    script.queue = [reply("Out of time; here is what I have.")]
    ln, _ = lane()

    async def go():
        t = await ln.start("research", minutes=1)
        t.started -= 120  # two minutes have passed
        await t.task
        return t
    t = asyncio.run(go())
    assert tools_seen == [None] and "Your time (1 min) is up" in script.seen[-1][-1].content
    assert t.state == "done"


def test_cancel(script, root):
    item, entered, _ = gate()
    script.queue = [item(reply("never"))]
    ln, notes = lane()

    async def go():
        t = await ln.start("research slowly")
        await entered.wait()
        res = await bg.run_command(ln, {"action": "cancel", "id": t.id})
        return t, res
    t, res = asyncio.run(go())
    assert t.state == "cancelled" and "cancelled" in res.output
    assert payloads(t.id, "background.cancelled")[0]["reason"] == "cancelled by human"
    assert not (t.folder / "report.md").exists()
    assert "background.completed" not in kinds(t.id)


def test_steer_opens_the_next_step_and_finish_asks_for_the_write_up(tools_seen, script, root):
    item, entered, release = gate()
    script.queue = [item(call("know", {"query": "x"}, cid="k1")), reply("Done, with the note in mind.")]
    ln, _ = lane()

    async def go():
        t = await ln.start("research x", steps=10)
        await entered.wait()
        await bg.run_command(ln, {"action": "steer", "note": "focus on prices in Bangladesh"})
        await bg.run_command(ln, {"action": "finish"})
        release.set()
        await t.task
        return t
    t = asyncio.run(go())
    second = script.seen[1]
    notes = [m.content for m in second if getattr(m, "role", None) == "user"]
    assert any(n.startswith("[NOTE FROM THE HUMAN") and "prices in Bangladesh" in n for n in notes)
    assert "The human asked you to finish now" in second[-1].content and tools_seen[1] is None
    assert "background.steered" in kinds(t.id) and t.state == "done"
    assert payloads(t.id, "background.completed")[0]["status"] == "SUCCESS"  # finished on the human's word, not cut


def test_every_brain_out_pauses_and_resumes(script, root, monkeypatch):
    monkeypatch.setattr(bg, "BRAIN_OUT_PAUSE_S", 0.01)

    async def out():
        raise BrainError("All brains failed. Gemini: cooling down (quota)")
    script.queue = [out, out, reply("Back, and done.")]
    ln, notes = lane()

    async def go():
        t = await ln.start("research")
        await t.task
        return t
    t = asyncio.run(go())
    assert t.state == "done" and len(payloads(t.id, "background.paused")) == 2
    assert len(payloads(t.id, "background.resumed")) == 2
    assert any("paused: every brain is out" in n for n in notes.notices())


def test_a_long_outage_fails_the_task(script, root, monkeypatch):
    monkeypatch.setattr(bg, "BRAIN_OUT_PAUSE_S", 0.01)
    monkeypatch.setattr(bg, "BRAIN_OUT_RETRIES", 1)

    async def out():
        raise BrainError("All brains failed.")
    script.queue = [out, out]
    ln, _ = lane()

    async def go():
        t = await ln.start("research")
        await t.task
        return t
    t = asyncio.run(go())
    assert t.state == "failed" and payloads(t.id, "background.failed")[0]["error_class"] == "brain"


def test_at_most_two_at_once(script, root):
    item, entered, release = gate()
    item2, entered2, _ = gate()
    script.queue = [item(reply("a")), item2(reply("b"))]
    ln, _ = lane()

    async def go():
        a = await ln.start("one")
        await entered.wait()
        b = await ln.start("two")
        await entered2.wait()
        res = await bg.run_command(ln, {"action": "start", "instruction": "three"})
        await ln.cancel_all("test over")
        return res
    res = asyncio.run(go())
    assert res.error and "at most 2" in res.error


def test_emergency_stop_refuses_a_start_and_stops_a_running_task(script, root):
    item, entered, _ = gate()
    script.queue = [item(reply("never"))]
    core = core_mod.get_core()

    async def go():
        t = await core.background.start("research while the operator watches")
        await entered.wait()
        await server.emergency_stop(core, "test", "operator")
        refused = await bg.run_command(core.background, {"action": "start", "instruction": "again"})
        return t, refused
    t, refused = asyncio.run(go())
    assert t.state == "cancelled" and payloads(t.id, "background.cancelled")[0]["reason"] == "emergency stop"
    assert refused.error and "emergency stop" in refused.error
    estop.clear_stop(get_journal(), "test over")


def test_an_emergency_stop_set_elsewhere_ends_it_at_the_next_step(script, root):
    item, entered, release = gate()
    script.queue = [item(call("know", {"query": "x"}, cid="k1")), reply("never")]
    ln, _ = lane()

    async def go():
        t = await ln.start("research")
        await entered.wait()
        estop.set_stop(get_journal(), "from the phone page")
        release.set()
        await t.task
        return t
    t = asyncio.run(go())
    assert t.state == "cancelled" and len(script.queue) == 1  # the second brain call was never made
    estop.clear_stop(get_journal(), "test over")


def test_the_chat_answers_while_a_background_task_runs(script, root):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    item, entered, release = gate()
    script.queue = [item(reply("Background report.")), reply("Chat answer while research runs.")]

    async def go():
        t = await core.background.start("research for a long time")
        await entered.wait()
        assert not core.busy  # the lane never makes SYRAX busy
        tid = await core.submit("hi", said="hi", session_id=None)
        assert tid is not None
        await core.wait()
        chat = core.journal.task(tid)
        still = t.state
        release.set()
        await t.task
        return chat, still, t
    chat, still, t = asyncio.run(go())
    assert chat["status"] == "SUCCESS" and chat["result"] == "Chat answer while research runs."
    assert still == "running" and t.state == "done"


def test_the_chat_tool_starts_it_and_a_restart_marks_it_interrupted(script, root):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    assert core.agent.available_tools.get_tool("background") is not None
    _, entered, _ = gate()

    class Waiting:  # the lane's own brain here: the chat's script stays the chat's (the two would race for it)
        async def ask_tool(self, **kw):
            entered.set()
            await asyncio.sleep(3600)

    core.background.router_factory = Waiting
    script.queue = [call("background", {"action": "start", "instruction": "research X in the background", "minutes": 999}, cid="b1"),
                    reply("Started it in the background."), reply("Background task started."), reply("Background task started.")]

    async def go():
        tid = await core.submit("research X in the background", said="research X in the background", session_id=None)
        await core.wait()
        t = next(iter(core.background.tasks.values()))
        await entered.wait()
        fresh = bg.BackgroundLane(core.journal, Notes())  # as after a restart: the task is not in this process
        interrupted = await fresh.settle_after_boot()
        await core.background.cancel_all("test over")
        return core.journal.task(tid), t, interrupted
    chat, t, interrupted = asyncio.run(go())
    assert chat["status"] == "SUCCESS" and t.minutes == bg.MAX_MINUTES  # 999 minutes is capped
    assert interrupted == [t.id]
