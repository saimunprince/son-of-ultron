"""EVOLUTION_PLAN wave 2 (directions 37 environment prediction, 94 tool selection): SYRAX called a tool without any
expectation of the outcome, and after a failure of a tool that fails most of the time here it often retried the same
call. Each call now carries the failure rate the journal predicted (scored in calibrate as a tool Brier score), and a
tool that fails at least 60% of over 5 real calls is named as such after it fails, once per task."""

from syrax import calibrate
from syrax.agent import FLAKY_NOTE
from syrax.journal import Journal, get_journal
from syrax.test_bridge import ORIGIN, TestClient, boot, call, drain_until_idle, reply, script, server  # noqa: F401


def calls(j, name, ok, n, output="Error: boom"):
    t = j.start_task_sync(f"use {name}")
    for i in range(n):
        j.record_sync("tool.started", {"id": f"{name}{ok}{i}", "name": name, "args": {}}, task_id=t)
        j.record_sync("tool.completed" if ok else "tool.failed",
                      {"id": f"{name}{ok}{i}", "name": name, "ok": ok, "output": "fine" if ok else output}, task_id=t)


def test_priors_are_smoothed_failure_rates_without_the_callers_mistakes(tmp_path):
    j = Journal(tmp_path / "j.db")
    calls(j, "weather", True, 8)
    calls(j, "weather", False, 2)
    calls(j, "pdf_text", False, 4, output="Error: x.txt is not a PDF")  # misuse: not the tool's failure
    priors = calibrate.tool_priors(j)
    assert priors["weather"] == (round(3 / 12, 3), 10)
    assert priors["pdf_text"] == (0.5, 0)


def test_a_call_carries_its_prediction_and_a_flaky_tool_is_named_after_it_fails(script):
    j = get_journal()
    calls(j, "python_execute", False, 9, output="Error: the python_execute worker died")
    script.queue = [call("python_execute", {"code": "raise SystemExit(3)"}, "Trying."),
                    call("python_execute", {"code": "raise SystemExit(4)"}, "Again."), reply("Could not.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "run the failing script"})
        seen = drain_until_idle(ws)
    results = [e for e in seen if e.get("type") == "tool_result" and e.get("name") == "python_execute"]
    assert results and all(isinstance(r.get("predicted_failure"), float) for r in results)
    notes = [r for r in results if "fails about" in (r.get("output") or "")]
    assert len(notes) == 1  # named once per task, not after every failure
    head = FLAKY_NOTE.split("{name}")[0].strip()
    assert head in notes[0]["output"]


def test_the_tool_predictions_are_scored(tmp_path):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("scored")
    j.record_sync("tool.completed", {"id": "a", "name": "weather", "ok": True, "output": "fine", "predicted_failure": 0.2}, task_id=t)
    j.record_sync("tool.failed", {"id": "b", "name": "weather", "ok": False, "output": "Error: boom", "predicted_failure": 0.8}, task_id=t)
    s = calibrate.summary(j)["tools"]
    assert s["n"] == 2 and s["brier"] == round((0.04 + 0.04) / 2, 4)
