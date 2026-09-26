"""End-to-end test of the SYRAX WebSocket bridge with a scripted fake LLM.

Run: OPENMANUS_DISABLE_BROWSER_USE=1 .venv/bin/python -m pytest syrax/test_bridge.py -q
"""

import asyncio
import json
import os

import tempfile  # noqa: E402

os.environ.setdefault("OPENMANUS_DISABLE_BROWSER_USE", "1")
_tmp_mem = __import__("tempfile").mkdtemp()
os.environ.setdefault("SYRAX_MEMORY_FILE", os.path.join(_tmp_mem, "memory.json"))
os.environ.setdefault("SYRAX_HISTORY_FILE", os.path.join(_tmp_mem, "history.jsonl"))
os.environ.setdefault("SYRAX_BROWSER", "0")
os.environ.setdefault("SYRAX_BRAINS_FILE", os.path.join(tempfile.mkdtemp(), "brains.json"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from openai.types.chat import ChatCompletionMessage  # noqa: E402
from openai.types.chat.chat_completion_message_tool_call import (  # noqa: E402
    ChatCompletionMessageToolCall,
    Function,
)

from syrax.brains import BrainRouter  # noqa: E402
from app.tool.base import BaseTool  # noqa: E402
from syrax import server  # noqa: E402
from syrax.agent import SyraxAgent  # noqa: E402

ORIGIN = {"origin": "http://localhost:3000"}


def reply(text):
    return ChatCompletionMessage(role="assistant", content=text)


def call(name, args, text="", cid=None):
    cid = cid or f"call_{name}_{abs(hash(json.dumps(args))) % 10000}"
    return ChatCompletionMessage(
        role="assistant",
        content=text,
        tool_calls=[
            ChatCompletionMessageToolCall(
                id=cid, type="function", function=Function(name=name, arguments=json.dumps(args))
            )
        ],
    )


class Script:
    def __init__(self):
        self.queue = []
        self.seen = []

    async def __call__(self, llm, messages, **kwargs):
        self.seen.append(messages)
        item = self.queue.pop(0)
        if callable(item):
            return await item()
        return item


class SlowTool(BaseTool):
    name: str = "slow"
    description: str = "sleeps"
    parameters: dict = {"type": "object", "properties": {}}

    async def execute(self):
        await asyncio.sleep(30)
        return "never"


@pytest.fixture
def script(monkeypatch):
    s = Script()

    async def fake(self, messages, **kwargs):
        return await s(self, messages, **kwargs)

    monkeypatch.setattr(BrainRouter, "ask_tool", fake)

    orig_create = SyraxAgent.create.__func__

    async def create(cls, **kw):
        agent = await orig_create(cls, **kw)
        agent.available_tools.add_tool(SlowTool())
        return agent

    monkeypatch.setattr(SyraxAgent, "create", classmethod(create))
    return s


def recv_until(ws, kind, limit=50):
    seen = []
    for _ in range(limit):
        e = ws.receive_json()
        seen.append(e)
        if e["type"] == kind:
            return e, seen
    raise AssertionError(f"no {kind} in {seen}")


def boot(ws):
    hello, _ = recv_until(ws, "hello")
    recv_until(ws, "state")
    return hello


def test_rejects_foreign_origin(script):
    client = TestClient(server.app)
    with pytest.raises(Exception):
        with client.websocket_connect("/ws", headers={"origin": "https://evil.example"}) as ws:
            ws.receive_json()


def boot_all(ws):
    hello, _ = recv_until(ws, "hello")
    brains, _ = recv_until(ws, "brains")
    recv_until(ws, "state")
    return hello, brains


def test_hello_and_brain_panel(script):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        hello, brains = boot_all(ws)
        ids = [p["id"] for p in brains["providers"]]
        assert "pollinations" in ids and "ollama" in ids and "gemini" in ids
        poll = next(p for p in brains["providers"] if p["id"] == "pollinations")
        assert poll["enabled"] and not poll["key_required"]
        ws.send_json({"type": "brains_save", "providers": {"gemini": {"api_key": "AIzaTESTKEY12345"}}})
        saved, _ = recv_until(ws, "brains")
        gem = next(p for p in saved["providers"] if p["id"] == "gemini")
        assert gem["has_key"] and gem["enabled"] and gem["key_hint"] == "••••2345"
        assert "AIzaTESTKEY12345" not in json.dumps(saved)  # key never echoed
        ws.send_json({"type": "brains_save", "providers": {"gemini": {"api_key": ""}}})
        cleared, _ = recv_until(ws, "brains")
        assert not next(p for p in cleared["providers"] if p["id"] == "gemini")["has_key"]


def test_chat_reply_ends_turn(script):
    script.queue = [reply("Ami SYRAX. Bol.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        hello = boot(ws)
        assert {"python_execute", "ask_human", "terminate"} <= set(hello["tools"])
        ws.send_json({"type": "task", "text": "ke tui?"})
        final, _ = recv_until(ws, "final")
        assert final["text"] == "Ami SYRAX. Bol."
        assert script.queue == []  # exactly one LLM call, no runaway loop


def test_tool_flow_streams_and_terminates(script):
    script.queue = [
        call("python_execute", {"code": "print(6*7)"}, "Hisab kortesi."),
        call("terminate", {"status": "success"}, "Uttor 42. Done."),
    ]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "6*7 koto?"})
        res, seen = recv_until(ws, "tool_result")
        assert res["name"] == "python_execute" and res["ok"] and "42" in res["output"]
        assert any(e["type"] == "state" and e.get("state") == "acting" for e in seen)
        final, _ = recv_until(ws, "final")
        assert final["text"] == "Uttor 42. Done."


def test_ask_human_roundtrip(script):
    script.queue = [
        call("ask_human", {"inquire": "Kon folder?"}),
        call("terminate", {"status": "success"}, "Thik ache."),
    ]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "file banao"})
        ask, _ = recv_until(ws, "ask")
        assert ask["question"] == "Kon folder?"
        ws.send_json({"type": "answer", "text": "workspace"})
        res, _ = recv_until(ws, "tool_result")
        assert "workspace" in res["output"]
        recv_until(ws, "final")


def test_abort_repairs_memory_and_next_task_works(script):
    script.queue = [call("slow", {}, cid="call_slow"), reply("Abar ready.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "wait"})
        recv_until(ws, "tool_start")
        ws.send_json({"type": "stop"})
        notice, _ = recv_until(ws, "notice")
        assert "aborted" in notice["text"].lower()
        recv_until(ws, "state")
        ws.send_json({"type": "task", "text": "abar?"})
        final, _ = recv_until(ws, "final")
        assert final["text"] == "Abar ready."
    # the dangling tool call must not be sent to the LLM again
    last = script.seen[-1]
    assert not any(getattr(m, "tool_calls", None) and m.tool_calls[0].id == "call_slow" for m in last)
    # and the model is told the old task was cancelled
    assert any("aborted the previous task" in (getattr(m, "content", "") or "") for m in last)


def test_python_execute_does_not_block_loop(script):
    script.queue = [
        call("python_execute", {"code": "import time; time.sleep(3); print('x')"}, cid="call_py"),
        reply("never reached"),
    ]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "sleep"})
        recv_until(ws, "tool_start")
        ws.send_json({"type": "ping"})
        pong, seen = recv_until(ws, "pong", limit=5)  # must arrive while code runs
        assert not any(e["type"] == "tool_result" for e in seen)
        ws.send_json({"type": "stop"})
        recv_until(ws, "notice")


def test_malformed_message_does_not_kill_session(script):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_text("not json")
        err, _ = recv_until(ws, "error")
        assert "Malformed" in err["message"]
        ws.send_json({"type": "ping"})
        recv_until(ws, "pong")


# ——— durable journal + core (task runs independently of the session) ———

from syrax.journal import Journal, get_journal  # noqa: E402
import syrax.journal as journal_mod  # noqa: E402
import syrax.core as core_mod  # noqa: E402


def drain_until_idle(ws, limit=80):
    seen = []
    for _ in range(limit):
        e = ws.receive_json()
        seen.append(e)
        if e["type"] == "state" and e.get("state") == "idle":
            return seen
    raise AssertionError(f"never idle: {seen}")


def test_chat_task_is_journaled_as_success_with_final_evidence(script):
    script.queue = [reply("Ami SYRAX. Bol.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        hello = boot(ws)
        assert hello["interrupted"] == [] and hello["running"] is None and hello["recent"] == []
        ws.send_json({"type": "task", "text": "ke tui?"})
        seen = drain_until_idle(ws)
    j = get_journal()
    task = j.tasks()[0]
    assert task["status"] == "SUCCESS" and task["result"] == "Ami SYRAX. Bol." and task["stage"] == "done"
    assert [e["type"] for e in j.events(task["task_id"])] == [
        "task.started", "think", "final", "checkpoint.created", "task.completed",
    ]
    started = [e for e in seen if e["type"] == "task" and e["event"] == "started"][0]
    assert started["task_id"] == task["task_id"]
    final = [e for e in seen if e["type"] == "final"][0]
    assert final["task_id"] == task["task_id"] and "event_id" in final
    assert any(e["type"] == "task" and e["event"] == "completed" and e["status"] == "SUCCESS" for e in seen)
    # the "user" echo stays direct and unchanged
    assert {"type": "user", "text": "ke tui?", "voice": False} in seen


def test_tool_task_records_steps_operation_and_checkpoints(script):
    script.queue = [
        call("python_execute", {"code": "print(6*7)"}, "Hisab kortesi."),
        call("terminate", {"status": "success"}, "Uttor 42. Done."),
    ]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "6*7 koto?"})
        seen = drain_until_idle(ws)
    j = get_journal()
    task = j.tasks()[0]
    kinds = [e["type"] for e in j.events(task["task_id"])]
    assert kinds[:4] == ["task.started", "think", "tool.started", "tool.completed"]
    assert kinds.count("checkpoint.created") == 3  # after python_execute, after terminate, at final
    assert task["status"] == "SUCCESS" and task["current_step"] == 2 and task["operation"] is None
    cps = j.checkpoints(task["task_id"])
    assert cps[0]["stage"] == "observed:python_execute"
    assert cps[0]["completed_steps"] == [{"step": 1, "tool": "python_execute", "id": cps[0]["completed_steps"][0]["id"], "ok": True}]
    assert any(m.get("role") == "tool" for m in cps[0]["context"])
    ts = [e for e in seen if e["type"] == "tool_start"][0]
    assert ts["step"] == 1 and ts["task_id"] == task["task_id"]
    assert any(e["type"] == "checkpoint" for e in seen)


def test_stop_journals_cancelled(script):
    script.queue = [call("slow", {}, cid="call_slow")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "wait"})
        recv_until(ws, "tool_start")
        ws.send_json({"type": "stop"})
        seen = drain_until_idle(ws)
    task = get_journal().tasks()[0]
    assert task["status"] == "CANCELLED" and task["error"] == "aborted by human"
    assert any(e["type"] == "task" and e["event"] == "cancelled" for e in seen)


def test_llm_error_journals_failed(script):
    async def boom():
        raise RuntimeError("brain melted")

    script.queue = [boom]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "x"})
        seen = drain_until_idle(ws)
    assert any(e["type"] == "error" and "brain melted" in e["message"] for e in seen)
    task = get_journal().tasks()[0]
    assert task["status"] == "FAILED" and "brain melted" in task["error"]


def test_tool_error_is_journaled_as_tool_failed_and_task_continues(script):
    script.queue = [
        call("python_execute", {"code": "raise ValueError('nope')"}),
        reply("It failed, as expected."),
    ]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "break"})
        drain_until_idle(ws)
    j = get_journal()
    task = j.tasks()[0]
    kinds = [e["type"] for e in j.events(task["task_id"])]
    assert "tool.failed" in kinds and task["status"] == "SUCCESS"
    assert j.checkpoints(task["task_id"])[0]["evidence_state"] == "PARTIAL"


def test_ask_blocks_then_answer_is_recorded(script):
    script.queue = [
        call("ask_human", {"inquire": "Kon folder?"}),
        call("terminate", {"status": "success"}, "Thik ache."),
    ]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "file banao"})
        recv_until(ws, "ask")
        j = get_journal()
        assert j.tasks()[0]["status"] == "BLOCKED" and j.tasks()[0]["operation"]["name"] == "ask_human"
        ws.send_json({"type": "answer", "text": "workspace"})
        user, _ = recv_until(ws, "user")
        assert user["text"] == "workspace" and "task_id" in user
        drain_until_idle(ws)
    task = get_journal().tasks()[0]
    kinds = [e["type"] for e in get_journal().events(task["task_id"])]
    assert "ask" in kinds and "answer" in kinds and task["status"] == "SUCCESS"


def test_task_survives_disconnect_and_reconnect_replays_it(script):
    script.queue = [
        call("python_execute", {"code": "import time; time.sleep(1.5); print('slow ok')"}, cid="call_py"),
        reply("Finished while you were away."),
    ]
    with TestClient(server.app) as client:  # one event loop for both connections
        with client.websocket_connect("/ws", headers=ORIGIN) as ws:
            boot(ws)
            ws.send_json({"type": "task", "text": "long job"})
            recv_until(ws, "tool_start")
        # browser gone; SYRAX keeps working
        core = core_mod.get_core()
        assert core.busy
        with client.websocket_connect("/ws", headers=ORIGIN) as ws2:
            hello, seen = recv_until(ws2, "hello")
            assert hello["running"]["goal"] == "long job" and hello["running"]["task_id"] == core.current.task_id
            replay, _ = recv_until(ws2, "task_events")
            assert [e["type"] for e in replay["events"]][:3] == ["task.started", "think", "tool.started"]
            state, _ = recv_until(ws2, "state")
            assert state["state"] in ("acting", "thinking")
            final, _ = recv_until(ws2, "final")
            assert final["text"] == "Finished while you were away."
            drain_until_idle(ws2)
        task = get_journal().tasks()[0]
        assert task["status"] == "SUCCESS" and task["current_step"] == 2
    # lifespan shutdown closed the journal; reopening sees the same durable truth
    assert get_journal().tasks()[0]["status"] == "SUCCESS"


def test_two_sessions_observe_the_same_task_and_only_one_may_run(script):
    script.queue = [
        call("python_execute", {"code": "import time; time.sleep(1); print('shared')"}),
        reply("Shared done."),
    ]
    with TestClient(server.app) as client:
        with client.websocket_connect("/ws", headers=ORIGIN) as a, client.websocket_connect("/ws", headers=ORIGIN) as b:
            boot(a)
            boot(b)
            a.send_json({"type": "task", "text": "shared job"})
            recv_until(b, "tool_start")
            b.send_json({"type": "task", "text": "me too"})
            notice, _ = recv_until(b, "notice")
            assert "Already executing" in notice["text"]
            fa, _ = recv_until(a, "final")
            fb, _ = recv_until(b, "final")
            assert fa["text"] == fb["text"] == "Shared done." and fa["event_id"] == fb["event_id"]
            drain_until_idle(a)
            drain_until_idle(b)
    assert len(get_journal().tasks()) == 1


def test_history_task_events_and_verifications_over_ws(script):
    script.queue = [reply("one"), reply("two")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        for text in ("first", "second"):
            ws.send_json({"type": "task", "text": text})
            drain_until_idle(ws)
        ws.send_json({"type": "history", "limit": 1})
        hist, _ = recv_until(ws, "history")
        assert [t["goal"] for t in hist["tasks"]] == ["second"] and hist["tasks"][0]["status"] == "SUCCESS"
        ws.send_json({"type": "task_events", "task_id": hist["tasks"][0]["task_id"]})
        ev, _ = recv_until(ws, "task_events")
        assert [e["type"] for e in ev["events"]][0] == "task.started"
        get_journal().record_verification_sync({"status": "GREEN", "gates": [{"name": "pytest", "status": "PASS", "required": True}]})
        ws.send_json({"type": "verifications"})
        v, _ = recv_until(ws, "verifications")
        assert v["verifications"][0]["status"] == "GREEN"
        ws.send_json({"type": "history", "limit": "garbage"})
        hist2, _ = recv_until(ws, "history")
        assert len(hist2["tasks"]) == 2


def seed_interrupted(tmp_path, target=None):
    """A previous process died mid str_replace_editor create. Returns task_id."""
    old = Journal(tmp_path / "journal.db", boot_id="dead-boot", recover=False)
    t = old.start_task_sync("write greeting file")
    old.record_sync("think", {"step": 1, "content": "writing"}, task_id=t)
    old.record_sync("tool.started", {
        "id": "e1", "name": "str_replace_editor",
        "args": {"command": "create", "path": str(target or tmp_path / "greeting.txt"), "file_text": "hello"},
        "step": 1,
    }, task_id=t)
    old.close()
    return t


def test_hello_lists_interrupted_task_with_verified_recovery_state(script, tmp_path):
    target = tmp_path / "greeting.txt"
    t = seed_interrupted(tmp_path, target)
    target.write_text("hello")  # the write actually landed before the crash
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        hello = boot(ws)
    assert len(hello["interrupted"]) == 1
    it = hello["interrupted"][0]
    assert it["task_id"] == t and it["step"] == 1 and it["tool"] == "str_replace_editor"
    assert it["recovery_state"] == "RESUMABLE" and it["operation_state"] == "COMPLETED"
    row = get_journal().task(t)
    assert row["status"] == "INTERRUPTED" and row["recovery"]["checks"]["operation"]["content_matches"] is True


def test_resume_continues_interrupted_task_with_restored_context(script, tmp_path):
    t = seed_interrupted(tmp_path)
    script.queue = [reply("Greeting file is there. Done.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        hello = boot(ws)
        assert hello["interrupted"][0]["recovery_state"] == "RESUMABLE"  # file missing → NOT_STARTED, safe to redo
        ws.send_json({"type": "resume", "task_id": t})
        resumed, _ = recv_until(ws, "recovery")
        assert resumed["event"] == "resumed" and resumed["task_id"] == t
        final, _ = recv_until(ws, "final")
        assert final["task_id"] == t
        drain_until_idle(ws)
        ws.send_json({"type": "resume", "task_id": t})
        notice, _ = recv_until(ws, "notice")
        assert "not INTERRUPTED" in notice["text"]
    row = get_journal().task(t)
    assert row["status"] == "SUCCESS" and row["result"] == "Greeting file is there. Done."
    kinds = [e["type"] for e in get_journal().events(t)]
    assert kinds[-7:] == ["recovery.verified", "task.interrupted", "recovery.resumed", "think", "final", "checkpoint.created", "task.completed"]
    # the model was told about the interruption and the operation state
    last_msgs = script.seen[-1]
    assert any("RESUMED AFTER INTERRUPTION" in (getattr(m, "content", "") or "") and "NOT_STARTED" in m.content for m in last_msgs)
    assert any("Continue the interrupted task: write greeting file" in (getattr(m, "content", "") or "") for m in last_msgs)


def test_resume_refuses_while_busy_and_unknown_task(script):
    script.queue = [call("slow", {}, cid="call_slow")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "resume", "task_id": "nope"})
        n, _ = recv_until(ws, "notice")
        assert "unknown task" in n["text"]
        ws.send_json({"type": "task", "text": "wait"})
        recv_until(ws, "tool_start")
        ws.send_json({"type": "resume", "task_id": "nope"})
        n, _ = recv_until(ws, "notice")
        assert "Already executing" in n["text"]
        ws.send_json({"type": "stop"})
        drain_until_idle(ws)


def test_journal_write_failure_never_fakes_success(script, monkeypatch):
    script.queue = [reply("I did answer.")]
    calls = {"n": 0}
    orig = Journal.record_sync

    def flaky(self, type_, payload=None, task_id=None, volatile=None, dedupe_key=None):
        calls["n"] += 1
        if calls["n"] >= 1:  # task.started goes through start_task_sync; every event write fails
            raise __import__("sqlite3").OperationalError("disk I/O error")
        return orig(self, type_, payload, task_id, volatile, dedupe_key)

    monkeypatch.setattr(Journal, "record_sync", flaky)
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "hi"})
        seen = drain_until_idle(ws)
        ws.send_json({"type": "ping"})
        recv_until(ws, "pong")  # session survives
    think = [e for e in seen if e["type"] == "think"][0]
    assert think.get("unjournaled") is True
    assert any(e["type"] == "error" and "Journal unavailable" in e["message"] for e in seen)
    assert not any(e["type"] == "final" for e in seen)  # reply was never certified
    monkeypatch.setattr(Journal, "record_sync", orig)
    task = get_journal().tasks()[0]
    assert task["status"] == "IN_PROGRESS"  # truthfully unresolved; next boot marks it INTERRUPTED


# ——— self-model ———


def test_self_model_over_ws_and_http_reflects_real_state(script):
    script.queue = [reply("I am SYRAX.")]
    client = TestClient(server.app)
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        hello = boot(ws)
        assert "self_inspect" in hello["tools"]
        ws.send_json({"type": "task", "text": "who are you"})
        drain_until_idle(ws)
        ws.send_json({"type": "self_model"})
        sm, _ = recv_until(ws, "self_model")
        assert sm["section"] == "summary" and sm["identity"]["name"] == "SYRAX"
        assert sm["tasks_by_status"] == {"SUCCESS": 1} and sm["running_task"] is None
        caps = {c["capability"] for c in sm["capabilities"]}
        assert caps == set(hello["tools"])  # registry = the tools actually registered
        ws.send_json({"type": "self_model", "section": "soul"})
        err, _ = recv_until(ws, "error")
        assert "unknown section" in err["message"]
    r = client.get("/self?section=behavior")
    assert r.status_code == 200 and r.json()["behavior"]["tasks_total"] == 1
    assert client.get("/self?section=nope").status_code == 400


def test_agent_can_inspect_itself_through_the_tool(script):
    script.queue = [
        call("self_inspect", {"section": "capabilities"}),
        reply("I have tools. Evidence attached."),
    ]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "what can you do?"})
        res, _ = recv_until(ws, "tool_result")
        assert res["name"] == "self_inspect" and res["ok"]
        body = res["output"].split("executed:\n", 1)[1]  # upstream prefixes tool output
        out = json.loads(body)
        assert any(c["capability"] == "python_execute" for c in out["capabilities"])
        drain_until_idle(ws)
    caps = {c["capability"]: c for c in core_mod.get_core().selfmodel.capabilities()}
    assert caps["self_inspect"]["status"] == "VERIFIED" and caps["self_inspect"]["uses"] == 1
