"""Daily briefing from the journal: what happened, nothing invented."""

import os
import time

os.environ.setdefault("OPENMANUS_DISABLE_BROWSER_USE", "1")

from syrax import briefing  # noqa: E402
from syrax.journal import Journal  # noqa: E402


def test_briefing_reports_only_what_the_journal_shows(tmp_path):
    j = Journal(tmp_path / "j.db")
    t0 = time.time() - 60
    t = j.start_task_sync("build make_docx", kind="autonomous")
    j.record_sync("final", {"text": "built"}, task_id=t)
    j.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t)
    o = j.add_objective_sync("Learn to make Word documents", source="human")
    j.update_objective_sync(o["id"], status="DONE", note="verified")
    j.upsert_skill_sync("make_docx", "Word documents", str(tmp_path), "VERIFIED", event="skill.verified")
    j.record_sync("proposal.created", {"limitation": "Core: one task at a time", "proposal": "Use a persistent task queue."})
    text = briefing.compose(j, t0)
    assert "1 finished, 0 failed" in text and "Learn to make Word documents" in text
    assert "new skills: make_docx" in text and "task queue" in text and "open objectives now: 0" in text
    assert "quality" not in text  # no run in the window: nothing claimed


def test_briefing_is_due_once_per_twelve_hours(tmp_path, monkeypatch):
    monkeypatch.setenv("SYRAX_BRIEFING", "1")
    j = Journal(tmp_path / "j.db")
    assert briefing.due(j)
    briefing.mark_shown(j)
    assert not briefing.due(j)
    assert briefing.due(j, now=time.time() + briefing.EVERY_S + 1)
