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


def test_mid_task_a_tight_brain_hands_over_instead_of_answering_without_tools(router, monkeypatch):
    """Quality run #22 (2026-11-04): with Gemini and Groq rate limited, Ollama got no tools mid-task and wrote
    'The todo application has been created' with nothing on disk. Once a tool has run, the next brain takes over."""
    from app.schema import ToolCall

    alpha = dataclasses.replace(brains.PROVIDERS["alpha"], max_request_tokens=700)
    monkeypatch.setattr(brains, "PROVIDERS", {**brains.PROVIDERS, "alpha": alpha})
    call = ToolCall(id="c1", type="function", function={"name": "extra_3", "arguments": "{}"})
    msgs = [Message.user_message("build the app " + "with care " * 160), Message.from_tool_calls([call]),
            Message.tool_message("ok " * 50, name="extra_3", tool_call_id="c1")]
    msg = ask(router, messages=msgs, tools=big_tools())
    body = [b for pid, b, _ in SEEN if pid == msg.content.split()[0]][-1]
    assert body.get("tools"), "mid-task a brain is never asked without tools"
    # so tight that not even the tools in use fit: alpha hands over instead of answering bare
    SEEN.clear()
    alpha = dataclasses.replace(brains.PROVIDERS["alpha"], max_request_tokens=560)
    monkeypatch.setattr(brains, "PROVIDERS", {**brains.PROVIDERS, "alpha": alpha})
    assert ask(router, messages=msgs, tools=big_tools()).content == "beta says hi"
