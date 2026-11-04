"""Live 2026-11-03: Ollama (4,096 tokens) failed with "request too large for this brain even after trimming: system
prompt + tools + latest turn ≈ 4419 tokens". The short persona and the essential tools alone did not fit, so the
local brain never answered. Two last steps now: only the tools the conversation is using (plus terminate), then a
plain answer without tools. Both are logged."""

import dataclasses

from app.schema import Message
from syrax import brains
from syrax.test_brains import SEEN, ask, base, router  # noqa: F401  (fixtures)


def big_tools(n=14):
    names = sorted(brains.ESSENTIAL_TOOLS) + [f"extra_{i}" for i in range(n)]
    return [{"type": "function", "function": {
        "name": nm, "description": f"{nm} " + "does a careful thing with many words. " * 30,
        "parameters": {"type": "object", "properties": {"x": {"type": "string", "description": "x " * 40}}}}}
        for nm in names]


def test_a_tight_brain_falls_back_to_the_tools_in_use_then_to_plain_chat(router, monkeypatch):
    alpha = dataclasses.replace(brains.PROVIDERS["alpha"], max_request_tokens=700)
    monkeypatch.setattr(brains, "PROVIDERS", {**brains.PROVIDERS, "alpha": alpha})
    msgs = [Message.user_message("please run the numbers " + "with care " * 160)]
    msg = ask(router, messages=msgs, tools=big_tools())
    assert msg.content == "alpha says hi"
    body = [b for pid, b, _ in SEEN if pid == "alpha"][-1]
    sent = [t["function"]["name"] for t in body.get("tools") or []]
    assert len(sent) <= 3  # terminate and at most the tools in use, or none at all
    assert brains.count_tokens(body["messages"]) + brains.count_tokens(body.get("tools") or []) < 700
