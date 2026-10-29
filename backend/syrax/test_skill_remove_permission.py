"""Live 2026-10-29 14:24 (autonomy, level 3): an objective "skill flight_search failed 12 of 15 uses: improve it" ended
with the task calling skill_test action=remove. The skill was disabled, DISABLED sticks until the human enables it,
and every boot since logged "disabled by the human". skill_test remove is now DESTRUCTIVE: own work and quality runs
are refused, a human request that names it goes through, any other human request asks first."""

from syrax import permissions as P


def remove(name="flight_search"):
    return P.classify("skill_test", {"name": name, "action": "remove"})


def test_removing_a_skill_is_destructive_and_testing_one_is_not():
    assert remove().level == P.DESTRUCTIVE and remove().targets == ["flight_search"]
    assert P.classify("skill_test", {"name": "flight_search"}).level == P.WRITE


def test_own_work_and_quality_runs_never_remove_a_skill():
    for kind in ("autonomous", "eval"):
        v = P.decide(remove(), kind, "Improve the flight_search skill: it failed 12 of 15 uses")
        assert v.action == "refuse", (kind, v)


def test_a_human_request_that_names_it_removes_it_and_another_asks_first():
    assert P.decide(remove(), "conversation", "remove the flight_search skill").action == "allow"
    assert P.decide(remove(), "conversation", "why do flights fail?").action == "ask"
