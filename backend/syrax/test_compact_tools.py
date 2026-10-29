"""Live 2026-10-29 (first Linux quality runs): Groq's free tier (8k tokens per request) refused every SYRAX request as
"too large" (~5.3k of it the tool manual), so when Gemini's quota ran out only Pollinations was left and tasks timed
out. A brain whose budget the full manual does not fit now gets the same tools with their first sentence and their
parameter schemas without prose; names, types, enums and required stay, so calls are the same calls."""

import asyncio

from syrax import brains
from syrax.agent import SyraxAgent


def tools():
    return SyraxAgent().available_tools.to_params()


def test_compact_tools_keep_every_name_type_and_requirement():
    full, small = tools(), brains.compact_tools(tools())
    assert brains.count_tokens(small) < brains.count_tokens(full) * 0.6
    for f, c in zip(full, small):
        ff, cf = f["function"], c["function"]
        assert ff["name"] == cf["name"] and len(cf["description"]) <= 200
        fp, cp = ff.get("parameters") or {}, cf.get("parameters") or {}
        assert sorted(fp.get("properties", {})) == sorted(cp.get("properties", {}))  # "description" as a NAME stays
        assert fp.get("required") == cp.get("required")
        for name, sub in fp.get("properties", {}).items():
            assert sub.get("type") == cp["properties"][name].get("type") and sub.get("enum") == cp["properties"][name].get("enum")
    named = [{"type": "function", "function": {"name": "t", "description": "Makes a thing from its parts. More prose here.",
              "parameters": {"type": "object", "properties": {"description": {"type": "string", "description": "the prose"}},
                             "required": ["description"]}}}]
    c = brains.compact_tools(named)[0]["function"]
    assert c["description"] == "Makes a thing from its parts." and c["parameters"]["properties"] == {"description": {"type": "string"}}


def test_an_8k_brain_gets_the_compact_manual_instead_of_refusing(monkeypatch):
    sent = {}

    class Client:
        class chat:
            class completions:
                @staticmethod
                async def create(**params):
                    sent.update(params)
                    raise brains.BrainError("stop here")

    router = brains.BrainRouter()
    monkeypatch.setattr(router, "_client", lambda pid: Client)
    monkeypatch.setattr(router, "_auto_model", lambda pid: asyncio.sleep(0, "m"))
    messages = [{"role": "system", "content": "word " * 2500}, {"role": "user", "content": "hi"}]  # ~2.5k-token prompt
    full = tools()
    assert brains.count_tokens(full) + 2600 + 1024 > brains.PROVIDERS["groq"].max_request_tokens  # the full manual cannot fit
    try:
        asyncio.run(router._call("groq", messages, full, "auto", False, model="m"))
    except Exception:
        pass
    assert sent, "the request was refused before it was sent"
    assert brains.count_tokens(sent["tools"]) < brains.count_tokens(full)
