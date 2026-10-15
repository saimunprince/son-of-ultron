"""Live 2026-10-15: the known-limitation cap (3 research objectives a day)
counted today's objectives in objectives(limit=200), ordered by priority then
age; with 262 rows the newest priority-3 ones fell outside the 200 and 7 got
through. Readers of "the newest" ask by creation time, readers of "every row"
are not cut at 500 (the catalog's taken keys, the DONE set dependencies wait
for)."""

import time

from syrax import catalog, limits
from syrax.journal import ALL_OBJECTIVES, Journal


def crowd(j, n, priority=1):
    for i in range(n):
        j.add_objective_sync(f"old work {i}", priority=priority, key=f"old:{i}")


def test_todays_known_limitations_are_counted_however_many_objectives_exist(tmp_path):
    j = Journal(tmp_path / "j.db")
    crowd(j, 230)
    for i in range(3):
        j.add_objective_sync(f"research limit {i}", priority=3, source="selfmodel", key=f"limit:known_limitation:x{i}:2026-W42")
    assert len(j.objectives_since(time.time() - 60)) == 233
    assert [o["key"] for o in j.objectives_since(time.time() - 60, limit=3)] == [f"limit:known_limitation:x{i}:2026-W42" for i in (2, 1, 0)]

    class SelfModel:
        def weaknesses(self):
            return [{"kind": "known_limitation", "detail": "Core: one task at a time"}]

    ranked = limits.rank(j, SelfModel())
    assert not [r for r in ranked if r["kind"] == "known_limitation"]  # the cap of 3 a day holds


def test_every_row_readers_are_not_cut_at_500(tmp_path):
    j = Journal(tmp_path / "j.db")
    crowd(j, 520)
    assert len(j.objectives(limit=ALL_OBJECTIVES)) == 520
    keys = {o.get("key") for o in j.objectives(limit=ALL_OBJECTIVES)}
    assert "old:519" in keys and catalog  # the catalog reads its taken keys this way
