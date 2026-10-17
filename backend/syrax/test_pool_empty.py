"""Live 2026-10-17: openrouter's chosen free model answered empty all morning;
the provider cooled down after each try and upstage, the weakest brain, took
the rest of quality run #46. A pooled provider whose model answers empty
twice (the second time with low reasoning) tries its other models first, and
the empty model rests half an hour."""

import asyncio

import pytest
from openai.types.chat import ChatCompletionMessage

from syrax import brains
from syrax.brains import BrainError, BrainRouter, Provider


@pytest.fixture
def router(monkeypatch, tmp_path):
    providers = {
        "pooled": Provider(id="pooled", label="Pooled", base_url="https://x/v1", tier="free", default_model="m-ultra", pool=True),
        "plain": Provider(id="plain", label="Plain", base_url="https://y/v1", tier="free", default_model="p1"),
    }
    monkeypatch.setattr(brains, "BRAINS_FILE", tmp_path / "brains.json")
    monkeypatch.setattr(brains, "PROVIDERS", providers)
    monkeypatch.setattr(brains, "DEFAULT_ORDER", ["pooled", "plain"])
    r = BrainRouter(brains.BrainStore(order=["pooled", "plain"], settings={"pooled": {"api_key": "k"}, "plain": {"api_key": "k"}}))
    r.calls, r.events = [], []
    empty = {"m-ultra", "m-mini"}

    async def fake_call(pid, messages, tools, tool_choice, images, model=None, extra=None):
        chosen = model or r.store.model(pid)
        r.last_model[pid] = chosen
        r.calls.append((pid, chosen))
        if pid == "pooled" and chosen in empty:
            raise BrainError("empty response")
        return ChatCompletionMessage(role="assistant", content=f"{pid}/{chosen}")

    async def fake_list(pid, key=None):
        return ["m-mini", "m-super", "m-ultra"]

    async def listen(event):
        r.events.append(event)

    monkeypatch.setattr(r, "_call", fake_call)
    monkeypatch.setattr(r, "list_models", fake_list)
    r.listeners.add(listen)
    return r


def ask(r):
    return asyncio.run(r.ask_tool(messages=[{"role": "user", "content": "hi"}]))


def test_an_empty_model_hands_over_to_another_pool_model(router):
    assert ask(router).content == "pooled/m-super"
    assert [m for p, m in router.calls if p == "pooled"][:2] == ["m-ultra", "m-ultra"]  # once, then once with low reasoning
    assert ("plain", "p1") not in router.calls  # the provider did not fail over
    assert any("m-ultra answers empty; answering with m-super" in str(e.get("text")) for e in router.events)
    router.calls.clear()
    assert ask(router).content == "pooled/m-super" and router.calls == [("pooled", "m-super")]  # m-ultra rests


def test_a_provider_without_the_pool_fails_over_as_before(router, monkeypatch):
    monkeypatch.setitem(brains.PROVIDERS, "pooled", brains.Provider(id="pooled", label="Pooled", base_url="https://x/v1", tier="free",
                                                                    default_model="m-ultra"))
    assert ask(router).content == "plain/p1"
