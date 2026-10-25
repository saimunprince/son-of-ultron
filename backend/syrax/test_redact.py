"""Audit 2026-10-25 ("Memory, skills, security"): secrets in logs and in the journal. redact.py holds the one
credential pattern; the server registers a loguru patcher once, so every log line is masked; core.emit masks the
journal's copy of every tool output (the UI shows that copy) while the agent's own event, and so the model's context,
keeps the real text."""

from loguru import logger

from syrax import redact, server
from syrax.agent import SyraxAgent
from syrax.test_bridge import ORIGIN, TestClient, boot, call, drain_until_idle, get_journal, script  # noqa: F401

# built by concatenation so the diff scan (verify.SECRET_PATTERNS) never sees a key shape in this file
GROQ = "gsk_" + "A1b2C3d4" * 3
OPENAI = "sk-" + "proj-" + "Zz9" * 8
GEMINI = "AIza" + "0q" * 18


def test_the_server_registers_the_patcher_once_and_every_log_line_is_masked():
    assert redact.install() is False  # already in place: syrax.server did it at import
    lines = []
    sink = logger.add(lines.append, format="{message}", level="DEBUG")
    try:
        logger.info(f"groq {GROQ} openai {OPENAI} gemini {GEMINI} plain words 12345 stay")
        logger.warning("nothing secret here")
    finally:
        logger.remove(sink)
    first, second = (str(x) for x in lines)
    assert first.count(redact.MASKED) == 3 and "plain words 12345 stay" in first
    assert GROQ not in first and OPENAI not in first and GEMINI not in first
    assert second.strip() == "nothing secret here"


def test_mask_keeps_non_text_and_plain_text_as_they_are():
    assert redact.mask("") == "" and redact.mask(None) is None and redact.mask(42) == 42
    assert redact.mask("no key in this sentence") == "no key in this sentence"
    assert redact.mask(f"key {GROQ}.") == f"key {redact.MASKED}."
    assert redact.CREDENTIAL is __import__("syrax.agent", fromlist=["CREDENTIAL"]).CREDENTIAL  # one pattern, two users


def test_the_journaled_tool_output_is_masked_while_the_agents_own_event_is_not(script, monkeypatch):
    own = []
    send = SyraxAgent._send

    async def spy(self, event):
        own.append(event)
        await send(self, event)

    monkeypatch.setattr(SyraxAgent, "_send", spy)
    script.queue = [
        call("python_execute", {"code": "print('gsk_' + 'A1b2C3d4' * 3)"}, "Printing."),
        call("terminate", {"status": "success"}, "Printed the sample."),
    ]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "print the sample string"})
        seen = drain_until_idle(ws)
    j = get_journal()
    done = [e for e in j.events(j.tasks()[0]["task_id"]) if e["type"] == "tool.completed"]
    journaled = done[0]["payload"]["output"]
    assert done[0]["payload"]["name"] == "python_execute" and GROQ not in journaled and redact.MASKED in journaled
    mine = [e for e in own if e["type"] == "tool_result" and e["name"] == "python_execute"][0]
    assert GROQ in mine["output"]  # the agent's event, what the model's context holds
    wire = [e for e in seen if e["type"] == "tool_result" and e["name"] == "python_execute"][0]
    assert GROQ not in wire["output"] and redact.MASKED in wire["output"]  # the UI sees the journal's copy
