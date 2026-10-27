"""Review 2026-10-27: at the loop limit the task ends with LOOP_STOPPED as its answer, but the words the brain wrote
beside the repeated call ("Checking myself again.") kept reply_before_action set, so the final-answer wrap-up
(FINAL_ASK) went out and its answer replaced the honest stop. A loop stop's answer stands."""

from syrax.agent import FINAL_ASK
from syrax.journal import get_journal
from syrax.test_agent_loops import run_task
from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, reply, script, server  # noqa: F401


def test_a_loop_stop_beside_words_keeps_its_honest_answer(script):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    same = {"action": "summary"}
    script.queue = [call("self_inspect", same, "Checking myself again.", cid=f"c{i}") for i in range(6)] + [
        reply("All good, everything inspected.")]
    task = run_task(core, "Inspect yourself")
    assert task["status"] == "PARTIAL"
    final = [e for e in get_journal().events(task["task_id"]) if e["type"] == "final"][-1]["payload"]["text"]
    assert final.startswith("Stopped: I called self_inspect with the same arguments 5 times in a row")
    assert task["result"].startswith("Stopped: I called self_inspect")
    assert not any(FINAL_ASK in str(m.content or "") for msgs in script.seen for m in msgs)
    assert len(script.queue) == 2  # the fifth repeat and the reply were never asked for
