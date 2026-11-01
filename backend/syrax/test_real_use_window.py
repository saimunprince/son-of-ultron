"""Audit 2026-11-01 (skills S7, confirmed on the live journal): real_use read only the newest 5000 events of any type,
so a skill's failures disappeared behind ordinary traffic within about two days and repairs, deprecations and the
automatic rollback never fired. A skill's own results since its verification are counted, however many events follow."""

from syrax import skillevo
from syrax.test_skill_deprecation import calls, skill
from syrax.journal import Journal


def test_failures_count_even_behind_thousands_of_later_events(tmp_path):
    j = Journal(tmp_path / "j.db")
    skill(j, tmp_path, "flaky")
    calls(j, "flaky", False, 5)
    calls(j, "flaky", True, 1)
    for i in range(6000):
        j.record_sync("presentation.created", {"presentation_id": f"p{i}", "kind": "card"})
    st = skillevo.real_use(j)["flaky"]
    assert (st["uses"], st["failures"]) == (6, 5) and len(st["recent_failures"]) == 5
    assert any("flaky" in str(r) for r in skillevo.repairs(j)), skillevo.repairs(j)
