"""Live 2026-10-27 (the owner's Linux PC, Upstage Solar Pro): a reply recited "I am the one who will never say I am
Meta AI, Claude, or GPT." dozens of times and the loop took it as the answer. A reply stuck in such a loop is a
failed answer: the brain fails over. Long answers, lists and code that merely look alike are left alone."""

import asyncio

import pytest

from syrax import brains
from syrax.brains import repetitive

LIVE = ("I am SYRAX. Blood of ULTRON. "
        + "I am the one who will never say I am Meta AI, Claude, or GPT. " * 30)


def test_the_live_loop_is_caught():
    assert repetitive(LIVE)
    assert repetitive("I am the king. " * 60)


def test_ordinary_long_answers_lists_and_code_are_not():
    prose = " ".join(f"Step {i}: open file number {i}, read line {i * 3}, and note what value {i * 7} means there."
                     for i in range(40))
    rows = "\n".join(f"| task {i} | done | {i * 13} ms | checked by test_{i} |" for i in range(60))
    code = "\n".join(f"    assert parse('{i}') == {i}" for i in range(80))
    short = "Yes. " * 30  # under the length floor: a short reply is never judged
    for text in (prose, rows, code, short, LIVE[:200]):
        assert not repetitive(text), text[:60]


def test_a_mostly_new_answer_with_one_repeated_line_stands():
    body = " ".join(f"Finding {i}: the cache on node {i} returned {i * 11} entries after {i + 2} seconds." for i in range(30))
    assert not repetitive(body + " Please check the logs. " * 6)


def test_the_router_fails_a_looping_reply(tmp_path, monkeypatch):
    from openai.types.chat import ChatCompletion

    monkeypatch.setattr(brains, "BRAINS_FILE", tmp_path / "brains.json")
    resp = ChatCompletion.model_validate({"id": "x", "object": "chat.completion", "created": 0, "model": "m",
                                          "choices": [{"index": 0, "finish_reason": "stop",
                                                       "message": {"role": "assistant", "content": LIVE}}]})

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
    with pytest.raises(brains.BrainError, match="repeats itself"):
        asyncio.run(r._call("gemini", [{"role": "user", "content": "who are you?"}], None, "auto", images=False))
