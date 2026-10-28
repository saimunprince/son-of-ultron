"""Measured 2026-10-28: Ollama's /v1 endpoint ignores options.num_ctx and cuts a longer prompt to the server's
context (4096 by default without VRAM) without saying so: a 12k-token prompt reached the model as 2,050 tokens and the
answer was invented. SYRAX budgeted 8192 for Ollama, so a 4-8k request went through and was cut the same way. The
budget is now the server's real context (SYRAX_OLLAMA_NUM_CTX), and a request that does not fit is refused, not sent."""

import os

import pytest

from syrax import brains


def test_the_ollama_budget_is_the_server_s_context_not_a_guess():
    assert brains.PROVIDERS["ollama"].max_request_tokens == int(os.getenv("SYRAX_OLLAMA_NUM_CTX", "4096"))
    if "SYRAX_OLLAMA_NUM_CTX" not in os.environ:
        assert brains.PROVIDERS["ollama"].max_request_tokens <= 4096


def test_a_request_beyond_it_is_refused_not_silently_cut():
    budget = brains.PROVIDERS["ollama"].max_request_tokens
    system = {"role": "system", "content": "word " * (budget * 2)}
    with pytest.raises(brains.BrainError, match="too large"):
        brains.fit_request([system, {"role": "user", "content": "hi"}], None, budget, 1024)
