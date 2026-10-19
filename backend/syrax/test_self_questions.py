"""Live 2026-10-13: Prince asked "how many capabilites you have?" and then "is it true?", and both answers were
"I am SYRAX. Blood of ULTRON. I have no limits." - no tool, no number, and a claim the journal contradicts (56 ranked
limitations on 2026-10-19). The console now says a question about SYRAX itself is read with self_inspect and answered
with its numbers, and quality case self_capabilities measures it."""

from syrax import quality
from syrax.prompt import SYRAX_PERSONA


def test_the_console_says_a_question_about_yourself_is_read_first():
    rule = next(line for line in SYRAX_PERSONA.splitlines() if line.startswith("- A question about yourself"))
    assert "`self_inspect` first" in rule and "Never claim to have no limits" in rule
    assert "- Simple talk or direct question: No tools." in SYRAX_PERSONA  # plain talk still needs none


def test_the_quality_case_fails_the_slogan_and_passes_an_answer_from_the_self_model(tmp_path):
    case = next(c for c in quality._cases(tmp_path) if c["id"] == "self_capabilities")
    read = [{"type": "tool.started", "payload": {"name": "self_inspect"}}]
    slogan = quality.check_case(case, {"status": "SUCCESS", "result": "I am SYRAX. Blood of ULTRON. I have no limits."}, [], {})
    assert [c["ok"] for c in slogan] == [False, False, False]  # no tool, no number, and "no limits"
    answer = quality.check_case(case, {"status": "SUCCESS", "result": "Thirty-one tools, 24 of them proven; 56 limitations ranked."}, read, {})
    assert all(c["ok"] for c in answer), answer
