"""journal_query: read-only SQL over SYRAX's own journal."""

import asyncio
import os

os.environ.setdefault("OPENMANUS_DISABLE_BROWSER_USE", "1")

from syrax import journal_query as jq  # noqa: E402
from syrax.journal import Journal  # noqa: E402


def test_select_works_writes_and_tricks_do_not(tmp_path):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("fix research_cite", kind="autonomous")
    j.record_sync("tool.failed", {"id": "c", "name": "python_execute", "ok": False, "output": "no such table: tool_calls"}, task_id=t)
    out = jq.run_query("SELECT json_extract(payload,'$.name') AS tool, count(*) AS n FROM events WHERE type='tool.failed' GROUP BY tool", tmp_path / "j.db")
    assert '"tool": "python_execute"' in out and '"n": 1' in out
    for bad in ("DELETE FROM tasks", "UPDATE tasks SET status='SUCCESS'", "SELECT 1; DELETE FROM tasks", "PRAGMA table_info(tasks)",
                "WITH x AS (SELECT 1) DELETE FROM tasks"):
        try:
            jq.run_query(bad, tmp_path / "j.db")
            raise AssertionError(f"ran: {bad}")
        except ValueError:
            pass
    assert j.task(t)["status"] == "IN_PROGRESS"
    assert "events(" in jq.schema_text(tmp_path / "j.db") and "payload" in jq.schema_text(tmp_path / "j.db")


def test_tool_reports_the_schema_on_a_bad_query(tmp_path, monkeypatch):
    Journal(tmp_path / "j.db")
    monkeypatch.setattr(jq, "_journal_path", lambda: tmp_path / "j.db")
    res = asyncio.new_event_loop().run_until_complete(jq.JournalQueryTool().execute(sql="SELECT * FROM tool_calls"))
    assert res.error and "no such table" in res.error and "tasks(" in res.error
