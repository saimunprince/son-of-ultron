"""Audit 2026-10-28: SYRAX had no emergency stop. WS `stop` cancelled only the running task (the autonomy loop picked
new work within one interval), `cycle_now` ran a cycle with autonomy off, and SYRAX_AUTONOMY=1 overrode the
operator's "off". The emergency stop (syrax.estop) is persistent, blocks every route by which SYRAX starts its own
work, survives a restart, and is set and cleared only by the operator's socket message."""

import asyncio

from fastapi.testclient import TestClient

from syrax import autonomy as auto
from syrax import estop, server
from syrax.devloop import JUDGES
from syrax.journal import Journal
from syrax.test_autonomy import make
from syrax.test_bridge import ORIGIN, boot, call, core_mod, drain_until_idle, get_journal, recv_until, script  # noqa: F401


def test_the_stop_holds_autonomy_off_even_forced_and_after_a_restart(tmp_path, monkeypatch):
    j, core, a = make(tmp_path)
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    monkeypatch.setenv("SYRAX_AUTONOMY", "1")
    a.set_enabled(True)
    assert a.enabled
    estop.set_stop(j, "test", "operator")
    assert not a.enabled
    for force in (False, True):  # cycle_now forces a cycle: never past the stop
        rep = asyncio.run(a.run_once(force=force))
        assert rep.outcome == "STOPPED" and "emergency stop" in rep.reason
    assert core.submitted == []
    a.start()
    assert a._loop_task is None  # the loop does not start
    j.close()
    j2 = Journal(tmp_path / "j.db")  # a restart reads the same journal
    assert estop.active(j2) and not auto.Autonomy(core, j2).enabled
    estop.clear_stop(j2, "done", "operator")
    assert auto.Autonomy(core, j2).enabled  # the operator's earlier "on" comes back; nothing else changed
    kinds = [e["type"] for e in j2.recent_events()]
    assert "estop.set" in kinds and "estop.cleared" in kinds


def test_the_environment_no_longer_overrides_the_operator_s_off(tmp_path, monkeypatch):
    j, core, a = make(tmp_path)
    monkeypatch.setenv("SYRAX_AUTONOMY", "1")
    assert a.enabled  # never chosen: the environment decides
    a.set_enabled(False)
    assert not a.enabled  # the operator chose: the environment may not turn it back on
    monkeypatch.setenv("SYRAX_AUTONOMY", "0")
    a.set_enabled(True)
    assert not a.enabled  # it may still force it off


def test_an_unreadable_stop_record_counts_as_on(tmp_path):
    j = Journal(tmp_path / "j.db")
    j.set_meta(estop.META_KEY, "{broken")
    assert estop.active(j)


def test_the_core_refuses_self_started_work_while_stopped_but_serves_the_human(script):
    j = get_journal()
    estop.set_stop(j, "test", "operator")
    try:
        core = core_mod.get_core()
        loop = asyncio.new_event_loop()
        for kind in ("autonomous", "eval"):
            assert loop.run_until_complete(core.submit("do own work", "do own work", None, kind=kind)) is None
        refused = [e for e in j.recent_events() if e["type"] == "estop.refused"]
        assert {e["payload"]["kind"] for e in refused} == {"autonomous", "eval"}
        script.queue = [call("terminate", {"status": "success"}, "Here.")]
        with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
            boot(ws)
            ws.send_json({"type": "task", "text": "hi"})
            drain_until_idle(ws)
        assert j.tasks()[0]["kind"] == "conversation"
    finally:
        estop.clear_stop(j, "test over", "operator")


def test_the_operator_message_stops_the_running_task_and_blocks_cycles(script):
    script.queue = [call("slow", {}, cid="call_slow")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "wait"})
        recv_until(ws, "tool_start")
        ws.send_json({"type": "estop", "on": True, "note": "smoke test"})
        st, seen = recv_until(ws, "autonomy_status", limit=120)
        assert st["estop"]["note"] == "smoke test" and st["enabled"] is False and st["running_loop"] is False
        if not any(e["type"] == "state" and e.get("state") == "idle" for e in seen):  # the cancel may end first
            drain_until_idle(ws)
        ws.send_json({"type": "cycle_now"})
        n, _ = recv_until(ws, "notice")
        assert "emergency stop is on" in n["text"]
        ws.send_json({"type": "autonomy", "enabled": True})
        n, _ = recv_until(ws, "notice")
        assert "clear it" in n["text"]
        st, _ = recv_until(ws, "autonomy_status")  # the answer to that request: still off
        assert st["enabled"] is False and st["estop"]
        ws.send_json({"type": "estop", "on": False})
        st, _ = recv_until(ws, "autonomy_status")
        assert st["estop"] is None
        ws.send_json({"type": "autonomy", "enabled": False})
        recv_until(ws, "autonomy_status")
    j = get_journal()
    stops = [e for e in j.recent_events() if e["type"] == "task.stop_requested"]
    assert stops and stops[0]["payload"]["reason"] == "emergency stop"


def test_own_code_cannot_clear_the_stop_through_the_journal(tmp_path):
    from syrax import tools

    journal_file = get_journal().path if hasattr(get_journal(), "path") else None
    out = asyncio.new_event_loop().run_until_complete(tools.AsyncPythonExecute().execute(code=(
        "import sqlite3, os\n"
        f"p = {str(journal_file)!r}\n"
        "c = sqlite3.connect(p)\n"
        "c.execute(\"INSERT OR REPLACE INTO meta(key, value) VALUES ('estop', '{\\\"on\\\": false}')\")\n"
        "c.commit()\nprint('WROTE')\n")))
    assert "WROTE" not in out["observation"], out


def test_the_controls_are_judges():
    for path in ("estop.py", "server.py", "core.py", "resources.py", "editor.py", "redact.py", "knowngood.py"):
        assert f"backend/syrax/{path}" in JUDGES
