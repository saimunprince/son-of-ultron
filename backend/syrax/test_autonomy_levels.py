"""Mission 2026-10-28 ("practical autonomy levels"), built 2026-10-29: the operator chooses how far SYRAX's own work
may go, from 1 (observe and research) to 5 (continuous); the level is a journal row own code cannot write, it is
enforced at the permission gate every tool call passes, and SYRAX cannot raise it."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from syrax import permissions as P
from syrax import server
from syrax.journal import get_journal
from syrax.test_autonomy import make
from syrax.test_bridge import ORIGIN, boot, call, core_mod, recv_until, reply, script  # noqa: F401


def d(tool, args=None):
    return P.classify(tool, args or {})


def test_each_kind_of_call_needs_its_level():
    repo_file = str(P.REPO_ROOT / "backend" / "syrax" / "x.py")
    work_file = str(P.WORKSPACE / "notes.md")
    assert P.level_needed(d("know", {"query": "x"})) == 1
    assert P.level_needed(d("research", {"question": "x"})) == 1
    assert P.level_needed(d("learn", {"claim": "x"})) == 1
    assert P.level_needed(d("python_execute", {"code": "print(1)"})) == 2
    assert P.level_needed(d("experiment", {})) == 2
    assert P.level_needed(d("str_replace_editor", {"command": "create", "path": work_file, "file_text": "x"})) == 2
    assert P.level_needed(d("str_replace_editor", {"command": "create", "path": repo_file, "file_text": "x"})) == 3
    assert P.level_needed(d("release", {"summary": "x"})) == 4


@pytest.mark.parametrize("level,allowed", [(1, {"know"}), (2, {"know", "python_execute"}),
                                           (3, {"know", "python_execute", "edit"}), (5, {"know", "python_execute", "edit", "release"})])
def test_own_work_is_held_to_the_operator_s_level(monkeypatch, level, allowed):
    monkeypatch.setattr(P, "OWN_LEVEL", level)
    calls = {"know": d("know", {"query": "x"}), "python_execute": d("python_execute", {"code": "print(1)"}),
             "edit": d("str_replace_editor", {"command": "create", "path": str(P.REPO_ROOT / "docs" / "n.md"), "file_text": "x"}),
             "release": d("release", {"summary": "x"})}
    for name, dec in calls.items():
        v = P.decide(dec, "autonomous", "")
        assert (v.action != "refuse" or "autonomy level" not in v.reason) == (name in allowed), (level, name, v)
        if name not in allowed:
            assert "only the operator raises it" in v.reason


def test_a_human_request_is_not_bound_by_it(monkeypatch):
    monkeypatch.setattr(P, "OWN_LEVEL", 1)
    v = P.decide(d("python_execute", {"code": "print(1)"}), "conversation", "run this")
    assert "autonomy level" not in (v.reason or "")


def test_the_level_is_stored_clamped_journaled_and_unset_means_five(tmp_path):
    j, core, a = make(tmp_path)
    assert a.level == 5 and a.status()["level"] == 5
    assert a.set_level(9, "test") == 5 and a.set_level(0, "test") == 1 and a.level == 1
    assert [e["payload"]["level"] for e in j.recent_events() if e["type"] == "autonomy.level_set"] == [5, 1]
    j.set_meta("autonomy_level", "high")
    assert a.level == 1  # unreadable: the most careful level


def test_level_one_own_task_cannot_run_code_end_to_end(script):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "autonomy_level", "level": 1})
        st, _ = recv_until(ws, "autonomy_status")
        assert st["level"] == 1
    core = core_mod.get_core()
    script.queue = [call("python_execute", {"code": "print('ran')"}, cid="p1"), reply("Could not: level 1.")]

    async def go():
        tid = await core.submit("[AUTONOMOUS OBJECTIVE] measure something", said="measure", session_id=None, kind="autonomous")
        await core.wait()
        return tid

    try:
        tid = asyncio.run(go())
        results = [e["payload"] for e in get_journal().events(tid) if e["type"] in ("tool.completed", "tool.failed")]
        assert results and "autonomy level 1" in str(results[0].get("output")) and "ran" not in str(results[0].get("output"))
        refused = [e for e in get_journal().events(tid) if e["type"] == "permission.refused"]
        assert refused
    finally:
        core.autonomy.set_level(5, "test cleanup")
