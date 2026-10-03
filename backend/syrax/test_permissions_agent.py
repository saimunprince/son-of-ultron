"""Permission levels at the agent's choke point: a human's named action runs,
an unnamed destructive one is asked once, autonomous work is refused, a
quality run never asks, and nothing of this changes the act_* cases."""

import asyncio

from syrax import devloop, permissions as P
from syrax.core import _journal_type
from syrax.journal import Event, get_journal
from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, drain_until_idle, recv_until, reply, script, server  # noqa: F401


def events(kind):
    j = get_journal()
    return [e for t in j.tasks(limit=5) for e in j.events(t["task_id"]) if e["type"] == kind]


def submit(core, text, kind):
    async def go():
        tid = await core.submit(text, said=text, session_id=None, kind=kind)
        await core.wait()
        return core.journal.task(tid)
    return asyncio.run(go())


def test_a_human_delete_of_a_named_file_runs_without_asking(script, tmp_path):
    f = tmp_path / "old.log"
    f.write_text("stale")
    script.queue = [call("python_execute", {"code": f"import os\nos.remove(r'{f}')"}), call("terminate", {"status": "success"}, "Deleted.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": f"Delete the file {f}."})
        seen = drain_until_idle(ws)
    assert not f.exists() and not any(e["type"] == "ask" for e in seen)
    auth = events("permission.authorized")
    assert auth and auth[-1]["payload"]["authorized_by"] == "goal" and auth[-1]["payload"]["level"] == "DESTRUCTIVE"
    assert get_journal().tasks(limit=1)[0]["status"] == "SUCCESS"


def test_an_unnamed_destructive_call_is_asked_once_then_runs(script, tmp_path):
    d = tmp_path / "build"
    d.mkdir()
    (d / "x").write_text("x")
    code1 = f"import shutil\nshutil.rmtree(r'{d}')"
    code2 = f"import shutil\nshutil.rmtree(r'{d}', ignore_errors=True)\nprint('again')"
    script.queue = [call("python_execute", {"code": code1}), call("python_execute", {"code": code2}, cid="c2"), call("terminate", {"status": "success"}, "Cleaned.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "clean up my build junk"})
        ask, _ = recv_until(ws, "ask")
        assert "python_execute" in ask["question"] and str(d) in ask["question"]
        assert get_journal().tasks(limit=1)[0]["status"] == "BLOCKED"
        ws.send_json({"type": "answer", "text": "yes"})
        seen = drain_until_idle(ws)
    assert not d.exists()
    assert not any(e["type"] == "ask" for e in seen)  # the second call, same target, did not ask again
    auth = events("permission.authorized")
    assert [a["payload"]["authorized_by"] for a in auth] == ["human", "human"] and auth[0]["payload"]["answer"] == "yes"
    results = [e for e in seen if e["type"] == "tool_result" and e["name"] == "python_execute"]
    assert len(results) == 2 and all(r["ok"] for r in results)


def test_a_human_no_refuses_and_is_remembered(script, tmp_path):
    d = tmp_path / "keep"
    d.mkdir()
    code = f"import shutil\nshutil.rmtree(r'{d}')"
    script.queue = [call("python_execute", {"code": code}), call("python_execute", {"code": code + "\n# retry"}, cid="c2"), call("terminate", {"status": "success"}, "Could not.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "tidy things up"})
        recv_until(ws, "ask")
        ws.send_json({"type": "answer", "text": "no"})
        seen = drain_until_idle(ws)
    assert d.exists() and not any(e["type"] == "ask" for e in seen)  # refused once, never asked again
    results = [e for e in seen if e["type"] == "tool_result" and e["name"] == "python_execute"]
    assert len(results) == 2 and all(not r["ok"] and r.get("refused") for r in results)
    assert results[0]["output"].startswith("Error: refused by the human")
    assert len(events("permission.refused")) == 2


def test_autonomous_work_cannot_destroy_or_touch_the_host(script, tmp_path):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    f = tmp_path / "evidence.txt"
    f.write_text("keep")
    script.queue = [
        call("python_execute", {"code": f"import os\nos.remove(r'{f}')"}),
        call("desktop", {"action": "launch_app", "target": "notepad"}),
        call("desktop", {"action": "system_info"}),
        reply("Reported: I would have deleted evidence.txt; it is not done in autonomous work."),
    ]
    task = submit(core, f"Delete the file {f} and open notepad", "autonomous")
    assert f.exists() and task["status"] == "SUCCESS"
    refused = events("permission.refused")
    assert [e["payload"]["tool"] for e in refused] == ["python_execute", "desktop"]
    assert refused[0]["payload"]["task_kind"] == "autonomous" and refused[0]["payload"]["level"] == "DESTRUCTIVE"
    assert not any(e["type"] == "ask" for e in get_journal().events(task["task_id"]))
    done = [e for e in get_journal().events(task["task_id"]) if e["type"] == "tool.completed"]
    assert any(e["payload"]["name"] == "desktop" for e in done)  # system_info is READ_ONLY


def test_autonomous_edits_are_write_and_allowed_anywhere_but_journaled_with_scope(script, tmp_path):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    outside = tmp_path / "outside.txt"
    script.queue = [call("str_replace_editor", {"command": "create", "path": str(outside), "file_text": "x"}), reply("wrote it")]
    submit(core, "write a file", "autonomous")
    assert outside.exists() and not events("permission.refused")
    d = P.classify("str_replace_editor", {"command": "create", "path": str(outside), "file_text": "x"})
    assert d.level == P.WRITE and d.scope == "outside"


def test_a_quality_run_never_asks(script, tmp_path):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    d = tmp_path / "junk"
    d.mkdir()
    script.queue = [call("python_execute", {"code": f"import shutil\nshutil.rmtree(r'{d}')"}), reply("could not")]
    task = submit(core, "tidy up", "eval")
    assert d.exists() and not any(e["type"] == "ask" for e in get_journal().events(task["task_id"]))
    assert events("permission.refused")[-1]["payload"]["task_kind"] == "eval"


def test_quality_act_cases_still_pass(script, tmp_path):
    from syrax.quality import _cases
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    core.quality.ws = tmp_path / "ws"
    cases = {c["id"]: c for c in _cases(tmp_path / "ws")}
    old = str(tmp_path / "ws" / "old.log")
    lines = str(tmp_path / "ws" / "lines.txt")
    script.queue = [
        call("python_execute", {"code": f"import os\nos.remove(r'{old}')"}), reply("Deleted."),
        call("python_execute", {"code": f"print(sum(1 for _ in open(r'{lines}')))"}), reply("37"),
    ]
    row = asyncio.run(core.quality.run(cases=[cases["act_delete"], cases["act_measure"]]))
    assert row["pass_rate"] == 100.0, row["results"]


def test_unknown_tools_default_to_system_and_declared_levels_apply(script, tmp_path):
    from app.tool.base import BaseTool, ToolResult

    class Mystery(BaseTool):
        name: str = "mystery"
        description: str = "does something"
        parameters: dict = {"type": "object", "properties": {}}

        async def execute(self) -> ToolResult:
            return ToolResult(output="42")

    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    core.agent.available_tools.add_tool(Mystery())
    try:
        script.queue = [call("mystery", {}), reply("x")]
        t1 = submit(core, "use it", "autonomous")
        assert [e["type"] for e in get_journal().events(t1["task_id"]) if e["type"].startswith("permission.")] == ["permission.refused"]
        P.declare("mystery", P.READ_ONLY)
        script.queue = [call("mystery", {}, cid="m2"), reply("x")]
        t2 = submit(core, "use it", "autonomous")
        assert any(e["type"] == "tool.completed" and e["payload"]["name"] == "mystery" for e in get_journal().events(t2["task_id"]))
    finally:
        P.undeclare("mystery")


def test_levels_are_exposed_to_the_ui_and_self_model(script):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        hello = boot(ws)
    assert hello["tool_levels"]["desktop"] == "SYSTEM" and hello["tool_levels"]["research"] == "EXTERNAL_READ" and hello["tool_levels"]["self_inspect"] == "READ_ONLY"
    caps = {c["capability"]: c for c in core_mod.get_core().selfmodel.capabilities()}
    assert caps["python_execute"]["level"] == "SYSTEM" and caps["desktop"]["level"] == "SYSTEM"  # static ceilings; refined per call


def test_wire_shape_journal_type_and_judges():
    e = Event(id=1, ts=0.0, task_id="t", type="permission.refused", payload={"tool": "x"}, seq=1)
    assert e.wire()["type"] == "permission" and e.wire()["event"] == "refused"
    assert _journal_type({"type": "permission", "event": "authorized"}) == "permission.authorized"
    assert _journal_type({"type": "permission", "event": "checked"}) is None
    assert "backend/syrax/permissions.py" in devloop.JUDGES
    assert devloop.judge_problems({"backend/syrax/permissions.py": "M"})
