"""Live 2026-10-28: Ollama qwen2.5-coder:7b on the OpenAI endpoint answered a tool request with the bare text
{"name": "calc", "arguments": {"expr": "17*23"}} and no tool call; the loop would take it for the final answer.
A reply that is nothing but a JSON call to an offered tool is a call; JSON inside an answer stays an answer."""

import json

from syrax.brains import text_tool_calls

TOOLS = [{"type": "function", "function": {"name": "calc"}}, {"type": "function", "function": {"name": "release"}}]


def test_the_bare_json_reply_from_the_live_check():
    calls, before = text_tool_calls('{"name": "calc", "arguments": {"expr": "17*23"}}', TOOLS)
    assert before == "" and len(calls) == 1 and calls[0].function.name == "calc"
    assert json.loads(calls[0].function.arguments) == {"expr": "17*23"}


def test_a_fenced_call_a_list_and_string_arguments():
    calls, _ = text_tool_calls('```json\n{"name": "calc", "arguments": "{\\"expr\\": \\"1+1\\"}"}\n```', TOOLS)
    assert json.loads(calls[0].function.arguments) == {"expr": "1+1"}
    calls, _ = text_tool_calls('[{"name": "calc", "arguments": {"expr": "2"}}, {"name": "release", "parameters": {"summary": "s"}}]', TOOLS)
    assert [c.function.name for c in calls] == ["calc", "release"] and json.loads(calls[1].function.arguments) == {"summary": "s"}


def test_json_that_is_not_only_an_offered_call_stays_an_answer():
    for text in ('The call looks like {"name": "calc", "arguments": {}}.',
                 '{"name": "rm_rf", "arguments": {}}',
                 '[{"name": "calc", "arguments": {}}, {"name": "rm_rf", "arguments": {}}]',
                 '{"city": "Tokyo", "temp": 21}',
                 '{"name": "calc", "arguments": [1, 2]}',
                 '{not json'):
        assert text_tool_calls(text, TOOLS) == ([], text), text
