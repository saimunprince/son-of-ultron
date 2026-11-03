"""Live 2026-11-01: Gemini answered HTTP 400 "function_response.name: Name cannot be empty" at contents[0]: the history
began with a tool result whose call was gone. OpenManus' Memory keeps its last 100 messages by slicing, which can
cut between a tool call and its result in the middle of a long task (SYRAX's own pair-safe trim runs only at a task's
start). The agent's memory now trims to a turn start, and the brain never sends a result without its call."""

from app.schema import Message, ToolCall

from syrax.agent import PairSafeMemory, SyraxAgent
from syrax.brains import _normalize_messages


def _call(i: int) -> Message:
    return Message.from_tool_calls([ToolCall(id=f"c{i}", type="function", function={"name": "bash", "arguments": "{}"})])


def test_the_agent_memory_never_starts_inside_a_tool_exchange():
    mem = PairSafeMemory(max_messages=10)
    mem.add_message(Message.system_message("persona"))
    for i in range(30):
        mem.add_message(Message.user_message(f"step {i}"))
        mem.add_message(_call(i))
        mem.add_message(Message.tool_message("ok", name="bash", tool_call_id=f"c{i}"))
    rest = [m for m in mem.messages if m.role != "system"]
    assert len(mem.messages) <= 10 and rest[0].role == "user"
    assert mem.messages[0].role == "system"  # the persona stays
    mem.add_messages([_call(99), Message.tool_message("ok", name="bash", tool_call_id="c99")])
    assert [m for m in mem.messages if m.role != "system"][0].role == "user"
    assert isinstance(SyraxAgent.model_fields["memory"].default_factory(), PairSafeMemory)


def test_the_brain_never_sends_a_result_without_its_call():
    msgs = [
        {"role": "system", "content": "persona"},
        {"role": "tool", "tool_call_id": "gone", "name": "", "content": "file written"},
        {"role": "user", "content": "go on"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "a", "type": "function",
                                                               "function": {"name": "bash", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "a", "content": "done"},
    ]
    out = _normalize_messages(msgs)
    assert [m["role"] for m in out] == ["system", "user", "user", "assistant", "tool"]
    assert "file written" in out[1]["content"]  # its text is kept, as a note
    assert out[4]["name"] == "bash"  # a result names its tool, from its call
