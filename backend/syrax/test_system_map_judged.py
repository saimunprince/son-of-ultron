"""Audit 2026-11-01 (F18): docs/system_map.json chooses which tests the release preflight runs and holds the known
limitations, yet as a docs file own work could change it, and a docs-only commit lands by replay without a new gate.
The judges guard it: own work cannot change it."""

from syrax import devloop


def test_the_system_map_is_guarded_like_a_judge():
    assert "docs/system_map.json" in devloop.JUDGED_DATA
    assert devloop.judge_problems({"docs/system_map.json": "M"})
    assert not devloop.judge_problems({"docs/RISE.md": "M"})  # the ledger's own docs stay releasable
