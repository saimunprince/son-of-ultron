"""Audit 2026-11-01 (self-improvement F5): when the worktree for SYRAX's own work could not be made, the task went on
in the running tree, and its release could commit straight onto the live branch. Own work that cannot be isolated
does not run: the task ends CANCELLED and the brain is never asked."""

import asyncio

from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, get_journal, script, server  # noqa: F401


def test_own_work_whose_worktree_fails_never_runs(script, monkeypatch):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    j = get_journal()
    monkeypatch.setenv("SYRAX_ISOLATE", "1")

    def broken(task_id):
        raise RuntimeError("git worktree add failed: disk full")

    monkeypatch.setattr(core.devloop, "isolate", broken)
    script.queue = [call("python_execute", {"code": "print('ran')"}, cid="c1"), call("terminate", {"status": "success"}, "done")]
    loop = asyncio.new_event_loop()
    try:
        assert loop.run_until_complete(core.submit("own work", "own work", None, kind="autonomous")) is None
        assert not core.busy and core.current is None
        task = j.tasks()[0]
        assert task["status"] == "CANCELLED"
        kinds = [e["type"] for e in j.events(task["task_id"])]
        assert "isolation.failed" in kinds and "tool.started" not in kinds and "think" not in kinds
        assert len(script.queue) == 2  # the brain was never asked
        cancelled = [e for e in j.events(task["task_id"]) if e["type"] == "task.cancelled"][-1]["payload"]
        assert "worktree could not be made" in cancelled["error"] and "disk full" in cancelled["error"]
    finally:
        loop.close()
