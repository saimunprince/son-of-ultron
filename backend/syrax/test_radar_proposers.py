"""Audit 2026-11-01 (skills S14): the radar ran the three skill proposers inside one try that swallowed every error,
and no skill proposal was ever journaled. Each runs on its own; a failing one is journaled as radar.error and the
others still run."""

import asyncio

from syrax import radar, skillevo
from syrax.journal import Journal
from syrax.test_radar import Router


def test_one_failing_proposer_does_not_stop_the_others_and_is_on_record(tmp_path, monkeypatch):
    j = Journal(tmp_path / "j.db")
    ran = []

    def boom(journal, now=None):
        raise RuntimeError("candidates broke")

    monkeypatch.setattr(skillevo, "propose_candidates", boom)
    monkeypatch.setattr(skillevo, "propose_deprecations", lambda journal, now=None: ran.append("deprecations") or 0)
    monkeypatch.setattr(skillevo, "propose_generalizations", lambda journal, now=None: ran.append("generalizations") or 0)
    monkeypatch.setenv("SYRAX_AUDIT", "0")
    out = asyncio.run(radar.scan(Router({"openrouter": ["a"]}), j))
    assert ran == ["deprecations", "generalizations"]
    assert "candidates broke" in out["skill_candidates"]["error"]
    errors = [e["payload"] for e in j.recent_events(100) if e["type"] == "radar.error"]
    assert errors and errors[0]["step"] == "skill_candidates"
