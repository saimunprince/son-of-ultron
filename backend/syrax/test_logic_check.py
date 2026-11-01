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


def test_quantifiers_are_named_and_ground_atoms_are_read():
    """Live 2026-11-01: a brain sent 'forall X (bird(X) -> fly(X))' and got "unexpected 'X'", which told it nothing.
    A quantifier now gets a clear first-order message with the way out; a ground atom like bird(tweety) is one name."""
    with pytest.raises(ValueError, match="propositional only.*bird\\(tweety\\)"):
        check(["forall X (bird(X) -> fly(X))", "bird(tweety)"], "fly(tweety)")
    with pytest.raises(ValueError, match="propositional only"):
        check(["exists x: p(x)"], "")
    r = check(["bird(tweety) -> fly(tweety)", "bird(tweety)"], "fly(tweety)")
    assert r["result"] == "ENTAILED" and r["vars"] == ["bird(tweety)", "fly(tweety)"]
    assert check(["loves(a, b)"], "loves(b, a)")["result"] == "NOT ENTAILED"
    err = asyncio.run(LogicCheckTool().execute(premises=["forall X (bird(X) -> fly(X))"], conclusion="fly(t)")).error
    assert "propositional only" in err
