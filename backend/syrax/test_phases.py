"""F4, the task phase model: the phase is read from what SYRAX does (events),
never from what the model says; each change reaches the UI live as a `phase`
message, the same path is recomputed from the journal alone (nothing new is
stored), and the snapshot a reconnecting UI reads carries the current phase."""

from syrax import permissions, phases
from syrax.devloop import JUDGES
from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, get_journal, reply, script, server  # noqa: F401


def walk(events):
    current, tools_run, out = None, 0, []
    for kind, ev in events:
        nxt = phases.after(current, kind, ev, tools_run)
        if kind == "tool.started":
            tools_run += 1
        if nxt:
            current = nxt["phase"]
            out.append((nxt["phase"], nxt.get("tool"), nxt.get("target")))
    return out


def test_the_phases_follow_the_events(tmp_path):
    f = str(tmp_path / "todo.md")
    seq = [
        ("think", {"step": 1, "tools": [{"name": "str_replace_editor"}]}),
        ("tool.started", {"name": "str_replace_editor", "args": {"command": "view", "path": f}, "step": 1}),
        ("think", {"step": 2, "tools": [{"name": "str_replace_editor"}]}),
        ("tool.started", {"name": "str_replace_editor", "args": {"command": "create", "path": f, "file_text": "x"}, "step": 2}),
        ("think", {"step": 3, "tools": [{"name": "release"}]}),
        ("tool.started", {"name": "release", "args": {"summary": "x"}, "step": 3}),
        ("think", {"step": 4, "tools": []}),
        ("final", {"text": "done"}),
    ]
    assert walk(seq) == [("plan", None, None), ("observe", "str_replace_editor", f), ("act", "str_replace_editor", f),
                         ("observe", None, None), ("verify", "release", None)]


def test_a_direct_answer_goes_straight_to_verify_and_quiet_tools_change_nothing():
    assert walk([("think", {"step": 1, "tools": []}), ("final", {"text": "Tokyo"})]) == [("verify", None, None)]
    assert phases.after("act", "tool.started", {"name": "terminate", "args": {}}, 3) is None
    assert phases.after("act", "tool.started", {"name": "ask_human", "args": {}}, 3) is None


def test_read_only_desktop_and_skills_observe_while_changes_act(monkeypatch):
    assert phases.phase_of_tool("desktop", {"action": "system_info"}) == "observe"
    assert phases.phase_of_tool("desktop", {"action": "launch_app", "target": "notepad"}) == "act"
    monkeypatch.setitem(permissions.DECLARED, "weather", permissions.EXTERNAL_READ)
    monkeypatch.setitem(permissions.DECLARED, "wallpaper", permissions.SYSTEM)
    assert phases.phase_of_tool("weather", {"place": "Dhaka"}) == "observe"
    assert phases.phase_of_tool("wallpaper", {"action": "set"}) == "act"
    assert phases.phase_of_tool("python_execute", {"code": "print(1)"}) == "observe"
    assert phases.phase_of_tool("python_execute", {"code": "open('x','w').write('y')"}) == "act"
    assert phases.after("observe", "tool.started", {"name": "weather", "args": {"place": "Dhaka"}}, 1) is None  # same phase


def test_a_task_journals_its_phases_and_the_ui_gets_them(script, tmp_path):
    target = tmp_path / "note.txt"
    script.queue = [
        call("str_replace_editor", {"command": "create", "path": str(target), "file_text": "hi\n"}),
        reply("Created note.txt."),
    ]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": f"Create {target} with hi in it"})
        seen = []
        for _ in range(80):
            e = ws.receive_json()
            seen.append(e)
            if e.get("type") == "task" and e.get("event") == "completed":
                break
    wire = [(e["phase"], e.get("from")) for e in seen if e.get("type") == "phase" and e.get("event") == "changed"]
    assert wire == [("understand", None), ("plan", "understand"), ("act", "plan"), ("observe", "act"), ("verify", "observe")]
    act = [e for e in seen if e.get("type") == "phase" and e.get("phase") == "act"][0]
    assert act["tool"] == "str_replace_editor" and act["target"].endswith("note.txt") and act["task_id"]
    tid = act["task_id"]
    events = get_journal().events(tid)
    assert not [e for e in events if e["type"].startswith("phase")]  # nothing new stored
    assert [(x["phase"], x.get("from")) for x in phases.path(events)] == wire  # the journal alone gives the same path


def test_the_ws_recomputes_a_tasks_phases_from_its_journal(script, tmp_path):
    script.queue = [reply("Tokyo.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "What is the capital of Japan?"})
        done = None
        for _ in range(60):
            e = ws.receive_json()
            if e.get("type") == "task" and e.get("event") == "completed":
                done = e
                break
        ws.send_json({"type": "task_phases", "task_id": done["task_id"]})
        for _ in range(20):
            e = ws.receive_json()
            if e.get("type") == "task_phases":
                break
    assert [x["phase"] for x in e["phases"]] == ["understand", "verify"] and all(x["event_id"] for x in e["phases"])


def test_the_snapshot_carries_the_phase_and_the_model_is_a_judge():
    assert "phase" in core_mod.Running.__dataclass_fields__
    assert "backend/syrax/phases.py" in JUDGES
    assert phases.PHASES == ("understand", "plan", "act", "observe", "verify")
