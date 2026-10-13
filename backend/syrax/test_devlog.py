"""M6: the devlog has one entry per day SYRAX ran, newest first, built from the
journal and git, and the daily ledger release publishes it next to RISE.md."""

import asyncio
import datetime as dt
import time

from syrax import devlog, ledger
from syrax import journal as jmod
from syrax.devloop import JUDGES
from syrax.journal import Journal
from syrax.test_ledger_publish import PASS, git, repo


def at(monkeypatch, ts):
    monkeypatch.setattr(jmod, "_now", lambda: ts)


def test_one_entry_per_day_that_ran_newest_first(tmp_path, monkeypatch):
    j = Journal(tmp_path / "j.db")
    now = time.time()
    noon = lambda days_ago: dt.datetime.combine(dt.date.fromtimestamp(now) - dt.timedelta(days=days_ago), dt.time(12)).timestamp()
    at(monkeypatch, noon(2))
    t = j.start_task_sync("tidy the desktop")
    j.record_sync("final", {"text": "tidied"}, task_id=t)
    j.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t)
    o = j.add_objective_sync("make the editor reliable", None, 3, "selfmodel", {"kind": "task_success"})
    j.update_objective_sync(o["id"], status="DONE", bump_attempts=True)
    j.record_sync("objective.completed", {"objective_id": o["id"], "status": "DONE"})
    j.add_quality_run_sync([{"id": "arith", "ok": True}, {"id": "build_cli", "ok": False}], 50.0, "REGRESSION", brain="gemini")
    at(monkeypatch, noon(0) if noon(0) < now else now - 60)
    u = j.start_task_sync("open notepad")
    j.record_sync("claim.rejected", {"text": "done"}, task_id=u)
    j.record_sync("task.failed", {"error": "x"}, task_id=u)
    j.record_sync("stall.recovered", {"silent_s": 70})
    at(monkeypatch, time.time)

    def commits(start, end):
        if start <= noon(2) < end:
            return [{"hash": "abc1234", "author": "SYRAX", "subject": "docs(rise): the ledger"},
                    {"hash": "def5678", "author": "Prince", "subject": "fix(editor): name the real file"}]
        return []

    days = devlog.entries(j, now=now, commits_of=commits)
    assert [d["day"] for d in days] == [dt.date.fromtimestamp(now).isoformat(), (dt.date.fromtimestamp(now) - dt.timedelta(days=2)).isoformat()]
    today, old = days
    assert today["failed"] == 1 and today["incidents"]["stalls"] == 1 and today["incidents"]["claims_sent_back"] == 1
    assert old["finished"] == 1 and old["closed"][0].startswith(f"#{o['id']} make the editor reliable")
    assert old["quality"]["failed"] == ["build_cli"] and [c["hash"] for c in old["own_commits"]] == ["abc1234"]
    text = devlog.render(days, "head123", generated="2026-10-13 18:00")
    assert text.startswith("# SYRAX devlog") and text.index(f"## {today['day']}") < text.index(f"## {old['day']}")
    assert "- Commits SYRAX made to itself: 1" in text and "`def5678` fix(editor): name the real file" in text
    assert "failed: build_cli" in text and "stalls 1" in text


def test_the_ledger_release_publishes_the_devlog_and_it_is_a_judge(tmp_path):
    root = repo(tmp_path)
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("a day of work")
    j.record_sync("final", {"text": "done"}, task_id=t)
    j.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t)
    rep = asyncio.run(ledger.publish(j, root=root, gates=lambda: PASS, now=time.time()))
    assert rep["outcome"] == "COMMITTED"
    log = (root / "docs" / "DEVLOG.md").read_text(encoding="utf-8")
    assert log.startswith("# SYRAX devlog") and f"## {dt.date.today().isoformat()}" in log
    assert "docs/DEVLOG.md" in git(root, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert git(root, "log", "-1", "--format=%s").endswith(ledger.SUMMARY)
    assert "backend/syrax/devlog.py" in JUDGES
