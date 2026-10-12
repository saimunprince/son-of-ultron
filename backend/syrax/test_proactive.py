"""Proactive check-ins: only after the human has been quiet, only in the day,
not more often than the cooldown, only with something to say, and built from
the journal. Fixed clocks; no model."""

import asyncio
import datetime as dt

from syrax import proactive, reminders
from syrax.journal import Journal
from syrax import journal as jmod

NOON = dt.datetime(2026, 10, 12, 12, 0).timestamp()


def at(monkeypatch, ts):
    monkeypatch.setattr(jmod, "_now", lambda: ts)


def human_talked(j, monkeypatch, ts):
    at(monkeypatch, ts)
    t = j.start_task_sync("hi")
    j.record_sync("final", {"text": "hello"}, task_id=t)
    j.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t)


def test_silence_when_there_is_nothing_new(tmp_path, monkeypatch):
    j = Journal(tmp_path / "j.db")
    human_talked(j, monkeypatch, NOON - 3 * 3600)
    at(monkeypatch, NOON)
    assert asyncio.run(proactive.tick(j, NOON)) is None and j.events_of_type("checkin.made") == []


def test_a_check_in_says_what_happened_while_the_human_was_away(tmp_path, monkeypatch):
    j = Journal(tmp_path / "j.db")
    human_talked(j, monkeypatch, NOON - 3 * 3600)
    at(monkeypatch, NOON - 3600)
    j.record_sync("skill.verified", {"skill": "json_tools", "status": "VERIFIED"})
    reminders.create(j, "call Rahim", NOON + 1800, now=NOON - 3600)
    at(monkeypatch, NOON)
    out = asyncio.run(proactive.tick(j, NOON))
    assert out["text"] == "While you were away: I built and verified json_tools; reminder at 12:30: call Rahim."
    assert asyncio.run(proactive.tick(j, NOON + 600)) is None  # cooldown


def test_never_while_the_human_is_active_or_at_night(tmp_path, monkeypatch):
    j = Journal(tmp_path / "j.db")
    human_talked(j, monkeypatch, NOON - 600)
    at(monkeypatch, NOON - 300)
    j.record_sync("skill.verified", {"skill": "x"})
    at(monkeypatch, NOON)
    assert asyncio.run(proactive.tick(j, NOON)) is None  # talked ten minutes ago
    night = dt.datetime(2026, 10, 12, 23, 30).timestamp()
    assert asyncio.run(proactive.tick(j, night)) is None
