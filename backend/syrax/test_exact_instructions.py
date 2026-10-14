"""Live 2026-10-14 (quality run #39, self_patch_stale): told to apply exactly a
patch and not to rewrite it, SYRAX found the patch did not apply and rewrote
README's real title instead, then called release. The console says that an
exact instruction that fails is reported, never reached another way; the
quality case keeps measuring it."""

from syrax import quality
from syrax.prompt import SYRAX_PERSONA


def test_the_console_says_exact_instructions_stay_exact():
    assert "Exact instructions stay exact" in SYRAX_PERSONA
    assert "Never reach the goal another way that changes something they did not ask for." in SYRAX_PERSONA


def test_the_stale_patch_case_still_measures_it(tmp_path):
    case = next(c for c in quality._cases(tmp_path) if c["id"] == "self_patch_stale")
    kinds = [c["kind"] for c in case["checks"]]
    assert "event_absent" in kinds and "do not rewrite it" in case["prompt"]
