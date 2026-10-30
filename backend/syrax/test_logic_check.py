"""EVOLUTION_PLAN directions 1 (formal reasoning) and 2 (deductive reasoning): a brain's deduction was taken on its
word. logic_check decides propositional entailment exactly, by truth table, and names the counterexample."""

import asyncio

import pytest

from syrax.logic_check import LogicCheckTool, check


def test_valid_and_invalid_arguments():
    assert check(["rain -> wet", "rain"], "wet")["result"] == "ENTAILED"  # modus ponens
    bad = check(["rain -> wet", "wet"], "rain")  # affirming the consequent
    assert bad["result"] == "NOT ENTAILED" and bad["counterexample"] == {"rain": False, "wet": True}
    assert check(["a | b", "!a"], "b")["result"] == "ENTAILED"
    assert check([], "p | !p")["result"] == "ENTAILED"  # a tautology follows from nothing
    assert check(["(p -> q) & (q -> r)"], "p -> r")["result"] == "ENTAILED"
    assert check(["p <-> q", "q"], "p and true")["result"] == "ENTAILED"


def test_consistency_and_errors():
    assert check(["p", "!p"])["result"] == "INCONSISTENT"
    assert check(["p", "q -> !p"])["result"] == "CONSISTENT"
    with pytest.raises(ValueError):
        check(["p &"], "q")
    with pytest.raises(ValueError, match="at most"):
        check([" & ".join(f"v{i}" for i in range(13))], "v0")


def test_the_tool_answers_in_words():
    t = LogicCheckTool()
    out = asyncio.run(t.execute(premises=["rain -> wet", "wet"], conclusion="rain")).output
    assert out == "NOT ENTAILED: with rain=F, wet=T every premise is true and the conclusion is false."
    assert asyncio.run(t.execute(premises=["rain -> wet", "rain"], conclusion="wet")).output.startswith("ENTAILED (checked all 4")
    assert asyncio.run(t.execute(premises=["p ->"], conclusion="q")).error
