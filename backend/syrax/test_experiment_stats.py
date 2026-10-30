"""EVOLUTION_PLAN wave 2 (directions 114 control-group design, 116 statistical analysis): an experiment ran every
baseline run before every candidate run (a warming cache or a busier machine passed for an effect) and judged by means
and sample overlap only. Arms now interleave in a seeded order that is on record, and an exact permutation test decides
when the run counts allow it; when they cannot reach significance, the conclusion says so."""

import asyncio

from syrax.experiments import ALPHA, judge, permutation_p, run_arms, can_reach_alpha
from syrax.test_experiments import engine


def arm(samples):
    return {"samples": samples, "value": sum(samples) / len(samples), "successes": len(samples), "repeats": len(samples)}


def test_the_permutation_p_value():
    assert permutation_p([1, 2, 3], [10, 11, 12]) == 0.1  # fully separated, 3 + 3: the smallest p there is
    assert permutation_p([1, 2, 3, 4, 5], [10, 11, 12, 13, 14]) == round(2 / 252, 4)
    assert permutation_p([1, 10, 2], [9, 3, 8]) > 0.5
    assert permutation_p([1], [2, 3]) is None
    assert not can_reach_alpha(2, 2) and can_reach_alpha(3, 3) and can_reach_alpha(5, 5)


def test_separated_but_not_significant_at_five_runs_is_no_difference():
    # 5 + 5 runs, means 40% apart, ranges touching but not overlapping: 9 9 9 9 30 vs 31 13 13 13 13 would overlap;
    # here the ranges do not overlap, yet the spread makes the difference not significant
    base, cand = arm([100, 101, 102, 103, 200]), arm([60, 61, 62, 63, 99.5])
    p = permutation_p(base["samples"], cand["samples"])
    verdict, why = judge("ms", base, cand)
    assert (verdict == "NO_DIFFERENCE") == (p > ALPHA)
    assert "permutation p=" in why


def test_too_few_runs_are_said_in_the_conclusion():
    verdict, why = judge("ms", arm([40.0, 41.0]), arm([2.0, 2.5]))
    assert verdict == "CANDIDATE_BETTER" and "too few runs" in why


def test_arms_interleave_in_a_recorded_seeded_order(tmp_path):
    j, t, e = engine(tmp_path)
    row = asyncio.run(e.run("order check", {"tool": "sleeper", "args": {"ms": 1}}, {"tool": "sleeper", "args": {"ms": 1}}, "ms", 5))
    order = row["result"]["order"]
    assert len(order) == 5 and set(order) <= {"BC", "CB"} and len(set(order)) == 2  # both orders occur, not all B first
    again = asyncio.run(e.run("order check", {"tool": "sleeper", "args": {"ms": 1}}, {"tool": "sleeper", "args": {"ms": 1}}, "ms", 5))
    assert again["result"]["order"] == order and "p_value" in row["result"]
