"""Live 2026-11-01: the review rejected a new skill (status FAILED, not registered), and the final answer said "I built
a factorial computation skill". It corrected itself only when the owner said "you are lied". A skill claimed as built
when no skill_create in the task was VERIFIED is sent back once, then replaced."""

import pytest

from app.tool.base import ToolResult
from syrax import skills
from syrax.claims import SKILL_FALLBACK, skill_claimed, skill_state
from syrax.test_bridge import call, reply, script  # noqa: F401  (script is a fixture)
from syrax.test_honest_claims import run_task

FAILED = ("skill `compute_factorial` v1: FAILED (3 passed, 0 failed)\nstage: review\nits tests passed, but a second "
          "brain did not approve the code: rejected\nNot registered. Fix the code or the tests and create it again with the same name.")
VERIFIED = "skill `compute_factorial` v1: VERIFIED (3 passed, 0 failed). It is registered now; call it by name like any other tool."


@pytest.mark.parametrize("text", [
    "I built a factorial computation skill.",
    "I've created a new skill called compute_factorial.",
    "Done: the compute_factorial skill is ready.",
    "Skill compute_factorial is now registered and available.",
])
def test_claims_of_a_built_skill(text):
    assert skill_claimed(text), text


@pytest.mark.parametrize("text", [
    "The factorial skill failed review and was not registered.",
    "I could not build the skill: a second brain rejected it.",
    "I built a skill, but it failed its tests.",
    "Your skills are listed below.",
])
def test_honest_answers_are_not_claims(text):
    assert not skill_claimed(text), text


def test_the_state_of_a_skill_create():
    assert skill_state("skill_create", FAILED) == "failed"
    assert skill_state("skill_create", VERIFIED) == "verified"
    assert skill_state("skill_create", "Error: skill_create refused: a skill for this exists") == "failed"
    assert skill_state("python_execute", VERIFIED) is None


def fake_create(monkeypatch, out):
    async def fake(self, name="", purpose="", code="", test_code="", **_):
        return ToolResult(output=out)

    monkeypatch.setattr(skills.SkillCreateTool, "execute", fake)


ARGS = {"name": "compute_factorial", "purpose": "factorials", "code": "class Skill: pass", "test_code": "def test_x(): pass"}


def test_a_built_skill_claimed_after_a_failure_is_replaced(script, monkeypatch):
    fake_create(monkeypatch, FAILED)
    script.queue = [
        call("skill_create", ARGS),
        call("terminate", {"status": "success"}, "I built a factorial computation skill."),
        reply("The compute_factorial skill is ready."),  # the rewrite repeats the claim
    ]
    assert run_task("make a factorial skill")["result"] == SKILL_FALLBACK and not script.queue


def test_a_verified_skill_may_be_claimed(script, monkeypatch):
    fake_create(monkeypatch, VERIFIED)
    script.queue = [
        call("skill_create", ARGS),
        call("terminate", {"status": "success"}, "I built a factorial computation skill."),
    ]
    assert run_task("make a factorial skill")["result"] == "I built a factorial computation skill."
