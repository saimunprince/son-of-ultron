"""EVOLUTION_PLAN wave 4 (directions 184 intrinsic reward, 185 exploration/exploitation, 187 uncertainty-driven
exploration, 188 curiosity prioritization): limits.rank valued a limitation by its kind's past success alone, so a kind
tried twice could never compete with one tried forty times at the same rate. An exploration bonus (UCB) now lifts kinds
with few attempts, and fades as they gather evidence."""

from syrax.limits import value_of


def st(done, total, calls=10.0):
    return {"done": done, "total": total, "calls": calls}


def test_a_rarely_tried_kind_outranks_a_well_known_one_at_the_same_rate():
    rare = value_of(0.6, st(1, 2), tried=42)
    known = value_of(0.6, st(20, 40), tried=42)
    assert rare[1] > known[1] and rare[3] > known[3]


def test_the_bonus_fades_with_attempts_and_success_is_never_above_one():
    bonuses = [value_of(0.6, st(n // 2, n), tried=100)[1] for n in (0, 4, 16, 64)]
    assert bonuses == sorted(bonuses, reverse=True)
    conf, bonus, cost, value = value_of(1.0, st(0, 0, calls=0.0), tried=1000)
    assert value <= 1.0
