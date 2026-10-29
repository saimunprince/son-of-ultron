"""Mission 2026-10-28 (learn by experiment), built 2026-10-29: an experiment's success criterion is declared before
either arm runs (min_effect_pct, never below the noise band) and is on record in experiment.started; and when both
arms ran at least twice and their samples overlap, the verdict is NO_DIFFERENCE however far apart the means are."""

import asyncio

from syrax.experiments import NOISE_PCT, judge
from syrax.test_experiments import engine


def arm(samples, successes=None):
    return {"samples": samples, "value": sum(samples) / len(samples), "successes": len(samples) if successes is None else successes,
            "repeats": len(samples)}


def test_overlapping_samples_are_no_difference():
    noisy_base, noisy_cand = arm([100, 20, 90]), arm([30, 95, 25])  # means 70 vs 50: -29 %, but the ranges overlap
    verdict, why = judge("ms", noisy_base, noisy_cand)
    assert verdict == "NO_DIFFERENCE" and "overlap" in why
    assert judge("ms", arm([100, 98, 101]), arm([50, 52, 49]))[0] == "CANDIDATE_BETTER"  # apart: a real difference


def test_the_declared_threshold_counts_and_cannot_go_below_the_noise_band():
    assert judge("ms", arm([100]), arm([60]), min_effect_pct=50)[0] == "NO_DIFFERENCE"  # 40 % < the 50 % declared
    assert judge("ms", arm([100]), arm([40]), min_effect_pct=50)[0] == "CANDIDATE_BETTER"
    assert judge("ms", arm([100]), arm([95]), min_effect_pct=1)[0] == "NO_DIFFERENCE"  # 1 % is raised to NOISE_PCT


def test_the_criterion_is_on_record_before_the_arms_run(tmp_path):
    j, t, e = engine(tmp_path)
    row = asyncio.run(e.run("smaller sleep is faster", {"tool": "sleeper", "args": {"ms": 40}}, {"tool": "sleeper", "args": {"ms": 2}},
                            "ms", 2, min_effect_pct=30))
    started = [ev for ev in j.events(t) if ev["type"] == "experiment.started"][-1]
    assert started["payload"]["min_effect_pct"] == 30
    assert row["result"]["min_effect_pct"] == 30 and row["verdict"] == "CANDIDATE_BETTER"
    started_default = asyncio.run(e.run("h", {"tool": "sleeper", "args": {"ms": 1}}, {"tool": "sleeper", "args": {"ms": 1}}, "ms", 1))
    assert started_default["result"]["min_effect_pct"] == NOISE_PCT
