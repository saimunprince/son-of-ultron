"""Live 2026-10-14 (objective 224, attempt 2): an openrouter model wrote its tool
call as text and the loop took the text for the final answer; the task ended
"SUCCESS" in the middle of the work. A call written in text, in either shape
open models use, is taken as a call, and only for tools that were offered."""

import json

from syrax.brains import text_tool_calls

TOOLS = [{"type": "function", "function": {"name": "str_replace_editor"}}, {"type": "function", "function": {"name": "release"}}]


def test_the_xml_shape_from_the_live_task():
    text = ("<tool_call> <function=str_replace_editor> <parameter=path> C:\\ai-agent\\son-of-ultron\\backend\\syrax\\memory.py "
            "</parameter> <parameter=command> view </parameter> <parameter=view_range> [1, 300] </parameter> </function> </tool_call>")
    calls, before = text_tool_calls(text, TOOLS)
    assert before == "" and len(calls) == 1 and calls[0].function.name == "str_replace_editor"
    args = json.loads(calls[0].function.arguments)
    assert args["command"].strip() == "view" and args["view_range"] == [1, 300] and args["path"].strip().endswith("memory.py")


def test_the_json_shape_and_text_before_it():
    text = 'Releasing now.\n<tool_call>{"name": "release", "arguments": {"summary": "expire stale inferences"}}</tool_call>'
    calls, before = text_tool_calls(text, TOOLS)
    assert before == "Releasing now." and json.loads(calls[0].function.arguments) == {"summary": "expire stale inferences"}


def test_a_multi_line_parameter_keeps_its_lines():
    text = "<tool_call><function=str_replace_editor><parameter=command>create</parameter><parameter=file_text>\nA = 1\nB = 2\n</parameter></function></tool_call>"
    args = json.loads(text_tool_calls(text, TOOLS)[0][0].function.arguments)
    assert args["file_text"] == "A = 1\nB = 2"


def test_unoffered_tools_and_plain_answers_are_left_alone():
    assert text_tool_calls('<tool_call>{"name": "rm_rf", "arguments": {}}</tool_call>', TOOLS)[0] == []
    assert text_tool_calls("Tokyo.", TOOLS) == ([], "Tokyo.")
    assert text_tool_calls("<tool_call>not json and no function</tool_call>", TOOLS)[0] == []


def test_the_router_turns_a_text_call_into_a_call(tmp_path, monkeypatch):
    import asyncio

    from openai.types.chat import ChatCompletion
    from syrax import brains

    monkeypatch.setattr(brains, "BRAINS_FILE", tmp_path / "brains.json")
    text = "<tool_call><function=release><parameter=summary>expire stale inferences</parameter></function></tool_call>"
    resp = ChatCompletion.model_validate({"id": "x", "object": "chat.completion", "created": 0, "model": "m",
                                          "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}]})

    class Client:
        def __init__(self):
            self.chat = type("C", (), {"completions": type("P", (), {"create": staticmethod(self.create)})()})()

        async def create(self, **params):
            return resp

        async def close(self):
            pass

    r = brains.BrainRouter.__new__(brains.BrainRouter)
    r.store, r.health, r.last_model = brains.BrainStore(), {p: brains.Health() for p in brains.PROVIDERS}, {}
    r.temperature, r.max_tokens, r.total_input_tokens, r.total_completion_tokens = 0.0, 100, 0, 0
    monkeypatch.setattr(r, "_client", lambda pid, key=None: Client())
    msg = asyncio.run(r._call("gemini", [{"role": "user", "content": "go"}], TOOLS, "auto", images=False))
    assert msg.content is None and len(msg.tool_calls) == 1
    assert msg.tool_calls[0].function.name == "release" and json.loads(msg.tool_calls[0].function.arguments) == {"summary": "expire stale inferences"}
