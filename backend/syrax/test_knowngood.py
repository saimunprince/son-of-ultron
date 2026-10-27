"""syrax.knowngood: what the launcher journals when it falls back to the known-good commit, through the journal's own
API: `restart.fallback` {from, to, why} and a reminder the known-good core fires once it runs (UI notice, spoken
line, desktop notification)."""

import asyncio
import json
import os

os.environ.setdefault("OPENMANUS_DISABLE_BROWSER_USE", "1")

from syrax import knowngood, reminders  # noqa: E402
from syrax.journal import Journal  # noqa: E402

X, K = "b" * 40, "a" * 40


def test_record_journals_the_event_and_a_notice(tmp_path):
    j = Journal(tmp_path / "journal.db", recover=False)
    try:
        out = knowngood.record(j, X, K, "the core did not answer /health within 180 s", now=1000.0)
        ev = j.events_of_type(knowngood.EVENT, limit=5)
        assert [e["payload"] for e in ev] == [{"from": X, "to": K, "why": "the core did not answer /health within 180 s"}]
        (r,) = reminders.pending(j)
        assert r["id"] == out["reminder"] and r["due_ts"] == 1000.0 + knowngood.NOTICE_AFTER_S
        assert X[:10] in r["text"] and K[:10] in r["text"] and "syrax.py --restart" in r["text"]
        assert len(r["text"]) <= reminders.MAX_TEXT
        told = []

        async def notify(text):
            told.append(text)

        fired = asyncio.run(reminders.fire_due(j, notify, now=1000.0 + knowngood.NOTICE_AFTER_S + 1))
        assert [f["id"] for f in fired] == [r["id"]] and told and "known-good" in told[0]
    finally:
        j.close()


def test_a_long_reason_still_fits_a_notice():
    text = knowngood.notice_text(X, K, "boom " * 200)
    assert len(text) <= reminders.MAX_TEXT and text.endswith("python syrax.py --restart")


def test_main_writes_the_journal_it_is_pointed_at(tmp_path, monkeypatch, capsys):
    path = tmp_path / "live.db"
    monkeypatch.setenv("SYRAX_JOURNAL_FILE", str(path))
    assert knowngood.main(["--from", X, "--to", K, "--why", "the core exited"]) == 0
    assert json.loads(capsys.readouterr().out)["to"] == K
    j = Journal(path, recover=False)
    try:
        assert j.events_of_type(knowngood.EVENT, limit=5)[0]["payload"]["from"] == X
    finally:
        j.close()


def test_main_never_writes_a_journal_a_running_core_owns(tmp_path, monkeypatch):
    class Owned:
        read_only = True
        closed = False

        def __init__(self, *a, **kw):
            pass

        def close(self):
            Owned.closed = True

    monkeypatch.setattr(knowngood, "Journal", Owned)
    monkeypatch.setattr(knowngood, "record", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("wrote")))
    assert knowngood.main(["--from", X, "--to", K]) == 2 and Owned.closed
