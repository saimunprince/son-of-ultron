"""Prince, 2026-10-29: agent.py (when a claim is checked, what a refused call returns, the tool budget) and brains.py
(which model answers and what it is shown) joined the judges. A self-release that edited either could switch a check
off without touching claims.py; now only a human commit changes them, and a brief that names them is refused before
anything runs."""

from syrax import devloop, repro

GOOD = '''"""x"""

from syrax.agent import named_tools


def test_a_forbidden_tool_is_not_requested():
    assert named_tools("Do not call release.", ["release"]) == []
'''


def test_agent_and_brains_are_judges():
    for path in ("backend/syrax/agent.py", "backend/syrax/brains.py"):
        assert path in devloop.JUDGES
        assert devloop.judge_problems({path: "M"}) == [f"{path}: this file judges SYRAX's own work; only a human changes it"]


def test_a_brief_naming_them_is_refused_before_it_runs():
    for path in ("backend/syrax/agent.py", "backend/syrax/brains.py"):
        problems = repro.screen("backend/syrax/test_named_forbidden.py", GOOD, [path])
        assert any("judges SYRAX's own work" in p for p in problems), problems
