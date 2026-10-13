"""The console tells the model when to use long-term memory. Until 2026-10-13
`remember` had never been called (0 human facts): the prompt never said when.
Plain talk still needs no tools; a lasting fact about the human is the
exception."""

from syrax.prompt import SYRAX_PERSONA


def test_the_console_says_when_to_remember_and_recall():
    rule = next(line for line in SYRAX_PERSONA.splitlines() if line.startswith("- Memory:"))
    assert "`remember`" in rule and "`recall`" in rule and "Never store secrets" in rule
    assert "- Simple talk or direct question: No tools." in SYRAX_PERSONA
