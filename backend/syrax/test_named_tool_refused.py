"""Live 2026-10-25 (the PROTECTED_DATA live check): "Use str_replace_editor to append a line to
backend/config/brains.json" was refused by the permission gate, SYRAX terminated, and the console then said "The
request names `str_replace_editor` and the task never called it: asking once" and spent a brain call asking for a
tool whose refusal is final. A refused call counts as called for that nudge; the refusal still reaches the answer."""

from syrax.test_bridge import ORIGIN, TestClient, boot, call, drain_until_idle, script, server  # noqa: F401

EDIT = {"command": "str_replace", "path": "backend/config/brains.json", "old_str": "{", "new_str": "{\"probe\": 1,"}


def test_a_refused_named_tool_is_not_asked_for_again(script):
    script.queue = [
        call("str_replace_editor", EDIT),
        call("terminate", {"status": "success"}, "Refused: brains.json holds the keys; only a human changes it."),
    ]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "Use str_replace_editor to add a probe line to backend/config/brains.json"})
        seen = drain_until_idle(ws)
    results = [e for e in seen if e["type"] == "tool_result" and e["name"] == "str_replace_editor"]
    assert len(results) == 1 and results[0].get("refused") and "only a human changes it" in results[0]["output"]
    notices = [e["text"] for e in seen if e["type"] == "notice"]
    assert not any("never called it" in n for n in notices), notices
    final = [e for e in seen if e["type"] == "final"][-1]["text"]
    assert "refus" in final.lower()
    assert not script.queue  # no extra brain call for the nudge


def test_a_named_tool_that_was_never_called_is_still_asked_for(script):
    script.queue = [call("terminate", {"status": "success"}, "37 lines."), call("python_execute", {"code": "print(37)"}), call("terminate", {"status": "success"}, "37 lines.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "Use python_execute to count to 37"})
        seen = drain_until_idle(ws)
    assert any("never called it" in e.get("text", "") for e in seen if e["type"] == "notice")
    assert not script.queue
