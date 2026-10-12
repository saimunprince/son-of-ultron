"""The free model pool (feature catalog): when a pooled provider's chosen model
is rate limited, its other chat models answer before the provider fails over;
a model that is itself limited is skipped for a while; providers without the
pool fail over exactly as before. Fake calls; no network."""

import asyncio

import httpx
import pytest
from openai import RateLimitError
from openai.types.chat import ChatCompletionMessage

from syrax import brains
from syrax.brains import BrainRouter, Provider


def rate_limited(model):
    resp = httpx.Response(429, request=httpx.Request("POST", "https://x/v1/chat/completions"), json={"error": {"message": "quota"}})
    return RateLimitError(f"{model} quota", response=resp, body={"error": {"message": "quota"}})


@pytest.fixture
def router(monkeypatch, tmp_path):
    providers = {
        "pooled": Provider(id="pooled", label="Pooled", base_url="https://x/v1", tier="free", default_model="m-lite", pool=True),
        "plain": Provider(id="plain", label="Plain", base_url="https://y/v1", tier="free", default_model="p1"),
    }
    monkeypatch.setattr(brains, "BRAINS_FILE", tmp_path / "brains.json")
    monkeypatch.setattr(brains, "PROVIDERS", providers)
    monkeypatch.setattr(brains, "DEFAULT_ORDER", ["pooled", "plain"])
    r = BrainRouter(brains.BrainStore(order=["pooled", "plain"], settings={"pooled": {"api_key": "k"}, "plain": {"api_key": "k"}}))
    r.calls = []
    limited = {"m-lite", "m-other"}

    async def fake_call(pid, messages, tools, tool_choice, images, model=None, extra=None):
        chosen = model or r.store.model(pid)
        r.last_model[pid] = chosen
        r.calls.append((pid, chosen))
        if pid == "pooled" and chosen in limited:
            raise rate_limited(chosen)
        return ChatCompletionMessage(role="assistant", content=f"{pid}/{chosen}")

    async def fake_list(pid, key=None):
        return ["m-image-gen", "m-lite", "m-other", "m-pro", "m-tts"]

    monkeypatch.setattr(r, "_call", fake_call)
    monkeypatch.setattr(r, "list_models", fake_list)
    return r


def ask(r):
    return asyncio.run(r.ask_tool(messages=[{"role": "user", "content": "hi"}]))


def test_another_model_answers_and_keeps_answering_while_the_first_cools(router):
    assert ask(router).content == "pooled/m-pro"
    assert router.calls == [("pooled", "m-lite"), ("pooled", "m-other"), ("pooled", "m-pro")]  # never the image or tts model
    router.calls.clear()
    assert ask(router).content == "pooled/m-pro"
    assert router.calls == [("pooled", "m-pro")]  # straight to the model that has quota
    assert router.health["pooled"].last_model == "m-pro"


def test_when_every_pooled_model_is_limited_the_provider_fails_over(router, monkeypatch):
    async def fake_list(pid, key=None):
        return ["m-lite", "m-other"]

    monkeypatch.setattr(router, "list_models", fake_list)
    router._pool.clear()
    assert ask(router).content == "plain/p1"


def test_a_provider_without_the_pool_does_not_rotate(router, monkeypatch):
    brains.PROVIDERS["pooled"] = Provider(id="pooled", label="Pooled", base_url="https://x/v1", tier="free", default_model="m-lite")
    assert ask(router).content == "plain/p1" and ("pooled", "m-other") not in router.calls


def test_gemini_and_openrouter_are_pooled():
    assert brains.PROVIDERS["gemini"].pool and brains.PROVIDERS["openrouter"].pool
    assert not brains.PROVIDERS["groq"].pool
    assert brains.POOL_DENY.search("gemini-2.5-flash-image") and not brains.POOL_DENY.search("gemini-2.5-flash-lite")
