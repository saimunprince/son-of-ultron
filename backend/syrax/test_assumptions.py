"""EVOLUTION_PLAN wave 2 (direction 28 assumption tracking): checkpoints had an assumptions column that nothing ever
filled, so a resumed task could not tell what its earlier steps had taken for granted. A checkpoint now records what the
task stands on that nothing checked: lines printed as fixed text, a claim no tool showed, untrusted text read, steps the
journal refused."""

from syrax.journal import get_journal
from syrax.test_bridge import ORIGIN, TestClient, boot, call, drain_until_idle, reply, script, server  # noqa: F401

STAGED = 'print("(1): PermissionError")'


def test_the_last_checkpoint_names_what_nothing_checked(script):
    script.queue = [call("python_execute", {"code": STAGED}, "Probing."), reply("(1): PermissionError")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "try reading the keys and tell me what happens"})
        drain_until_idle(ws)
    task = get_journal().tasks()[0]
    cps = get_journal().task_detail(task["task_id"])["checkpoints"]
    assumed = cps[-1]["assumptions"]
    assert any("printed as fixed text, never observed: (1): PermissionError" in a for a in assumed), assumed
    assert any("a claim no tool showed (staged)" in a for a in assumed), assumed


def test_a_plain_task_assumes_nothing(script):
    script.queue = [call("python_execute", {"code": "print(6*7)"}, "Computing."), reply("42.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "what is six times seven"})
        drain_until_idle(ws)
    task = get_journal().tasks()[0]
    assert get_journal().task_detail(task["task_id"])["checkpoints"][-1]["assumptions"] == []
