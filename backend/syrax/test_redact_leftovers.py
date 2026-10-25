"""Audit 2026-10-25 ("Memory, skills, security"), the leftovers after test_redact.py: the checkpoint context stored the
agent's raw messages (tool outputs and all), a logged exception's rendered traceback bypassed the loguru patcher
(which masked record["message"] only), and the human's own words (the task goal) and the model's `think` text were
journaled as they came, so a key the human pasted into a request landed in the journal. The journal's copies are
masked at write time; the text the agent works with (its memory, task_goal, the request the brain sees) is never
touched: the journal is evidence, the agent may need the key to do the work."""

import json

from loguru import logger

from syrax import redact
from syrax.test_bridge import (  # noqa: F401
    ORIGIN, TestClient, boot, call, core_mod, drain_until_idle, get_journal, recv_until, reply, script, server,
)

# built by concatenation so the diff scan (verify.SECRET_PATTERNS) never sees a key shape in this file
GROQ = "gsk_" + "A1b2C3d4" * 3
OPENAI = "sk-" + "proj-" + "Zz9" * 8


def test_mask_deep_walks_containers_and_keeps_their_shape():
    obj = {"content": f"key {GROQ}", "tool_calls": [{"function": {"arguments": json.dumps({"k": OPENAI})}}],
           "n": 3, "ok": True, "none": None, "t": ("a", GROQ)}
    out = redact.mask_deep(obj)
    dumped = json.dumps(out)
    assert GROQ not in dumped and OPENAI not in dumped and dumped.count(redact.MASKED) == 3
    assert out["n"] == 3 and out["ok"] is True and out["none"] is None and out["t"] == ["a", redact.MASKED]
    assert obj["content"] == f"key {GROQ}"  # the source is untouched: a new copy comes back
    assert redact.mask_deep("plain") == "plain" and redact.mask_deep(7) == 7 and redact.mask_deep(None) is None


def test_the_checkpoint_context_and_tool_args_are_masked_while_the_agents_memory_keeps_the_key(script):
    script.queue = [
        call("python_execute", {"code": "print('gsk_' + 'A1b2C3d4' * 3)"}, "Printing."),
        call("python_execute", {"code": f"print(len('{GROQ}'))"}, "Measuring."),
        call("terminate", {"status": "success"}, "Printed the sample."),
    ]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "print the sample string"})
        drain_until_idle(ws)
    j = get_journal()
    tid = j.tasks()[0]["task_id"]
    cps = j.checkpoints(tid)
    assert len(cps) >= 2 and any(cp["stage"] == "final" for cp in cps)
    stored = json.dumps([cp["context"] for cp in cps])
    assert GROQ not in stored and redact.MASKED in stored  # every stored copy of the context is masked
    events = j.events(tid)
    started = [e for e in events if e["type"] == "tool.started" and e["payload"]["name"] == "python_execute"]
    assert GROQ not in started[1]["payload"]["args"]["code"] and redact.MASKED in started[1]["payload"]["args"]["code"]
    done = [e for e in events if e["type"] == "tool.completed" and e["payload"]["name"] == "python_execute"]
    assert "28" in done[1]["payload"]["output"]  # the tool ran with the real key: len("gsk_" + 24 chars)
    live = json.dumps([m.to_dict() for m in core_mod.get_core().agent.memory.messages])
    assert GROQ in live  # the agent's own memory, what the model's context holds, keeps the key
    assert GROQ in str(script.seen[-1])  # and so did the brain on its last step


def test_a_logged_exception_is_rendered_masked_in_the_sink():
    redact.install()  # a no-op when syrax.server already did it
    lines = []
    sink = logger.add(lines.append, format="{message}", level="DEBUG")
    try:
        try:
            raise RuntimeError(f"auth failed for {GROQ}")
        except RuntimeError:
            logger.exception("request failed")
        try:
            raise ValueError(OPENAI)
        except ValueError:
            logger.opt(exception=True).warning("second")
        logger.info("no exception here")
    finally:
        logger.remove(sink)
    first, second, third = lines
    assert "request failed" in first and "Traceback" in first and "RuntimeError" in first
    assert GROQ not in first and redact.MASKED in first
    assert first.record["exception"] is None  # the sink has nothing unmasked left to render
    assert "second" in second and "ValueError" in second and OPENAI not in second and redact.MASKED in second
    assert str(third).strip() == "no exception here" and third.record["exception"] is None


def test_a_key_in_the_humans_request_is_masked_in_the_journal_but_not_for_the_agent(script):
    seen_goal = []

    async def answer():
        seen_goal.append(core_mod.get_core().agent.task_goal)
        return reply(f"ok, the config holds {GROQ}")

    script.queue = [answer]
    request = f"the config has {GROQ}, say ok"
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": request})
        seen = drain_until_idle(ws)
    j = get_journal()
    row = j.tasks()[0]
    assert GROQ not in row["goal"] and redact.MASKED in row["goal"]
    events = j.events(row["task_id"])
    started = [e for e in events if e["type"] == "task.started"][0]
    assert GROQ not in started["payload"]["goal"] and redact.MASKED in started["payload"]["goal"]
    think = [e for e in events if e["type"] == "think"][0]
    assert GROQ not in think["payload"]["content"] and redact.MASKED in think["payload"]["content"]
    wire = [e for e in seen if e["type"] in ("task.started", "think")]
    assert wire and all(GROQ not in json.dumps(e) for e in wire)  # the UI sees the journal's copies
    assert seen_goal == [request]  # the agent works with the human's real words
    assert GROQ in str(script.seen[-1])  # and the brain was asked with them


def test_a_queued_requests_journal_row_is_masked_and_it_still_starts_with_the_real_words(script):
    seen_goal = []

    async def second():
        seen_goal.append(core_mod.get_core().agent.task_goal)
        return reply("Second done.")

    script.queue = [
        call("python_execute", {"code": "import time; time.sleep(1); print('first')"}),
        reply("First done."),
        second,
    ]
    request = f"then use {GROQ} for the second job"
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "first job"})
        recv_until(ws, "tool_start")
        ws.send_json({"type": "task", "text": request, "queue": True})
        notice, seen = recv_until(ws, "notice")
        assert notice["text"].startswith("Queued (position 1)")
        queued = [e for e in seen if e["type"] in ("queue", "task.queued")]
        assert queued and all(GROQ not in json.dumps(e) for e in queued)
        recv_until(ws, "final")
        recv_until(ws, "final")
        drain_until_idle(ws)
    j = get_journal()
    row = next(r for r in j.tasks(limit=5) if r["goal"] != "first job")
    assert GROQ not in row["goal"] and redact.MASKED in row["goal"] and row["status"] == "SUCCESS"
    events = j.events(row["task_id"])
    assert [e["type"] for e in events][:2] == ["task.queued", "task.started"]
    assert GROQ not in json.dumps([e["payload"] for e in events])
    assert seen_goal == [request]
