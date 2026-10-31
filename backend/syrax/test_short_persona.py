"""Live 2026-10-31: Ollama (4,096 tokens) refused every request, the full system prompt alone being ~3,000 tokens.
A brain that cannot fit the full prompt even with tools chosen per request gets the short persona: the same identity,
language rule, console and hard rules in few words. Every other brain keeps the full one."""

from syrax.brains import SHORT_SYSTEMS, count_tokens, register_short_system, shorten_system
from syrax.prompt import SYRAX_PERSONA, SYRAX_PERSONA_SHORT


def test_the_short_persona_keeps_the_rules_and_is_small():
    short = SYRAX_PERSONA_SHORT.format(directory="/w")
    for must in ("SYRAX", "Bengali script", "current message decides", "ask_human", "Error: refused", "terminate",
                 "self_inspect", "remember", "/w"):
        assert must in short, must
    assert count_tokens(short) < 450 < count_tokens(SYRAX_PERSONA.format(directory="/w")) / 3


def test_a_registered_prompt_is_replaced_only_in_system_messages():
    SHORT_SYSTEMS.clear()
    register_short_system("FULL PROMPT " * 50, "SHORT")
    m = [{"role": "system", "content": "FULL PROMPT " * 50 + "\n\n=====\n\nmcp manual"}, {"role": "user", "content": "FULL PROMPT"}]
    out = shorten_system(m)
    assert out[0]["content"] == "SHORT\n\n=====\n\nmcp manual" and out[1] == m[1]
    assert shorten_system([{"role": "system", "content": "other"}]) is None
    for i in range(40):
        register_short_system(f"full {i} " * 9, "s")
    assert len(SHORT_SYSTEMS) <= 16
