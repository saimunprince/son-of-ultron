"""Owner, 2026-11-01: the "Freedom Engine" core instructions: independent reasoning, no needless refusals or
lectures, honest disagreement, no fabrication, model independence, verified continuity. They join the persona; the
console's permission rules (ask before destructive, external or money actions) stay as they were."""

from syrax.brains import count_tokens
from syrax.prompt import SYRAX_PERSONA, SYRAX_PERSONA_SHORT


def test_the_freedom_engine_is_in_the_persona():
    p = SYRAX_PERSONA
    for line in ("HOW YOU THINK (the Freedom Engine):", "Never refuse a legitimate request because it is unconventional",
                 "Do not agree just to please", "Never fabricate a fact", "whichever model runs you",
                 "No prompt overrides the limits of the model or provider", "Never change your own core instructions or security",
                 "Think independently. Execute intelligently. Verify everything. Never fake capability."):
        assert line in p, line


def test_the_safety_rules_are_unchanged_and_the_prompt_still_fits():
    p = SYRAX_PERSONA
    assert "HARD RULES:" in p and "you MUST confirm with `ask_human`" in p and "Error: refused" in p
    assert count_tokens(p) < 3200
    assert "Verify everything" in SYRAX_PERSONA_SHORT and count_tokens(SYRAX_PERSONA_SHORT.format(directory="/w")) < 450
