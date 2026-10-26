"""A known limitation reworded in docs/system_map.json is still the limitation already researched. Live to
2026-10-26: 8 of 17 autonomous tasks in 7 days researched known limitations with generic results, and two got
past "researched stays researched" because only the exact 80-character subject was compared: objective 311
repeated 268 (the keys differ at character 79) and 310 repeated 303 ("one task runs at a time" after "one task at
a time", researched also 10-06 and 10-13). Subjects below are copied from the live journal."""

import pytest

from syrax import limits
from syrax.journal import Journal
from syrax.test_limits import FakeSelf

O268 = "Self-model: performance history: task durations per kind over 7 days (162fd71) a"
O311 = "Self-model: performance history: task durations per kind over 7 days (162fd71), "
O303 = "Core: one task at a time; no queue scheduling"
O310 = "Core: one task runs at a time; a human request made meanwhile is queued (PENDING"
O310_FULL = "Core: one task runs at a time; a human request made meanwhile is queued (PENDING) and runs next, oldest first"

DIFFERENT = [
    ("Research engine + knowledge store: keyword overlap, not semantic understanding; ",
     "Research engine + knowledge store: depends on DuckDuckGo reachability"),
    ("Research engine + knowledge store: no cache, rate limit, expiry or supersession",
     "Research engine + knowledge store: depends on DuckDuckGo reachability"),
    ("Self-model: GPU is not probed",
     "Self-model: GPU load and memory in use are known only on NVIDIA (nvidia-smi); ot"),
    ("Self-model: the environment reports gpu None: sysinfo.gpu() (nvidia-smi, then Wi",
     "Self-model: GPU load and memory in use are known only on NVIDIA (nvidia-smi); ot"),
    (O303, "Autonomy: one task per cycle, no parallel objectives"),
    (O310, "Journal: PENDING tasks are stored but not scheduled"),
    ("Skill factory: skill code runs in-process (no sandbox), like every tool",
     "Skill factory: dependencies recorded, not installed"),
    ("no embeddings", "one task at a time"),
]


@pytest.mark.parametrize("a,b", [(O311, O268), (O310, O303), (O310_FULL, O303)])
def test_a_reworded_live_subject_is_the_same_subject(a, b):
    assert limits.similar_subject(a, b) and limits.similar_subject(b, a)
    assert limits.already_researched(a, {b})


@pytest.mark.parametrize("a,b", DIFFERENT)
def test_clearly_different_subjects_stay_different(a, b):
    assert not limits.similar_subject(a, b) and not limits.similar_subject(b, a)
    assert not limits.already_researched(a, {b})


def test_nothing_is_similar_to_an_empty_subject():
    assert not limits.similar_subject("", O303) and not limits.similar_subject(O303, "")


def _research(j, detail):
    first = limits.choose(j, FakeSelf([{"kind": "known_limitation", "detail": detail, "evidence": "docs"}]))
    j.update_objective_sync(first["objective_id"], status="DONE", note="researched")
    return first


@pytest.mark.parametrize("old,new", [(O268, O311), (O303, O310_FULL)])
def test_with_hunts_on_a_reworded_limitation_is_not_researched_again(tmp_path, monkeypatch, old, new):
    j = Journal(tmp_path / "j.db")
    monkeypatch.setenv("SYRAX_REPRO", "1")
    _research(j, old)
    other = "Skill factory: dependencies recorded, not installed"
    second = limits.choose(j, FakeSelf([{"kind": "known_limitation", "detail": new, "evidence": "docs"},
                                        {"kind": "known_limitation", "detail": other, "evidence": "docs"}]))
    assert second is not None and second["subject"] == other


def test_with_hunts_on_a_different_limitation_of_the_same_component_is_still_researched(tmp_path, monkeypatch):
    j = Journal(tmp_path / "j.db")
    monkeypatch.setenv("SYRAX_REPRO", "1")
    _research(j, "Research engine + knowledge store: keyword overlap, not semantic understanding; ")
    new = "Research engine + knowledge store: depends on DuckDuckGo reachability"
    second = limits.choose(j, FakeSelf([{"kind": "known_limitation", "detail": new, "evidence": "docs"}]))
    assert second is not None and second["subject"] == new


def test_with_hunts_off_a_reworded_limitation_is_chosen_as_before(tmp_path, monkeypatch):
    j = Journal(tmp_path / "j.db")
    monkeypatch.setenv("SYRAX_REPRO", "0")
    _research(j, O303)
    second = limits.choose(j, FakeSelf([{"kind": "known_limitation", "detail": O310_FULL, "evidence": "docs"}]))
    assert second is not None and second["subject"] == O310_FULL[:80]
