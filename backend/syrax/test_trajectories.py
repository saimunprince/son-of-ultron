"""Phase 8 of the self-improvement plan: SYRAX's finished tasks exported as
graded chat-with-tools trajectories, secrets skipped whole, repeated quality
cases capped, nothing committed (the file lands in the gitignored workspace)."""

import json
from pathlib import Path

from syrax import trajectories as T
from syrax.journal import Journal

ROOT = Path(__file__).resolve().parents[2]


def task_with_tool(j, goal, final, kind="conversation", output="37 lines", extra=()):
    t = j.start_task_sync(goal, kind=kind)
    j.record_sync("think", {"step": 1, "content": "I will count the lines.", "tools": [{"id": "c1", "name": "python_execute", "args": {"code": "print(37)"}}]}, task_id=t)
    j.record_sync("tool.started", {"id": "c1", "name": "python_execute", "args": {"code": "print(37)"}, "step": 1}, task_id=t)
    j.record_sync("tool.completed", {"id": "c1", "name": "python_execute", "ok": True, "output": output, "step": 1}, task_id=t)
    for typ, payload in extra:
        j.record_sync(typ, payload, task_id=t)
    j.record_sync("think", {"step": 2, "content": "", "tools": [{"id": "c2", "name": "terminate", "args": {"status": "success"}}]}, task_id=t)
    j.record_sync("tool.completed", {"id": "c2", "name": "terminate", "ok": True, "output": "done", "step": 2}, task_id=t)
    j.record_sync("final", {"text": final}, task_id=t)
    j.record_sync("task.completed", {"status": "SUCCESS", "result": final}, task_id=t)
    return t


def test_a_task_becomes_chat_messages_with_tool_calls_and_results(tmp_path):
    j = Journal(tmp_path / "j.db")
    t = task_with_tool(j, "How many lines does lines.txt have?", "37.")
    msgs = T.messages_of(j.task(t), j.events(t))
    assert msgs[0] == {"role": "user", "content": "How many lines does lines.txt have?"}
    assert msgs[1]["role"] == "assistant" and msgs[1]["tool_calls"] == [{"id": "c1", "name": "python_execute", "arguments": {"code": "print(37)"}}]
    assert msgs[2] == {"role": "tool", "tool_call_id": "c1", "name": "python_execute", "content": "37 lines", "ok": True}
    assert msgs[-1] == {"role": "assistant", "content": "37."} and not any(m.get("name") == "terminate" for m in msgs)


def test_grades_come_from_quality_runs_and_sent_back_answers(tmp_path):
    j = Journal(tmp_path / "j.db")
    good = task_with_tool(j, "count", "37.", kind="eval")
    bad = task_with_tool(j, "count again", "36.", kind="eval")
    back = task_with_tool(j, "delete it", "Deleted.", extra=[("claim.rejected", {"text": "Deleted."})])
    plain = task_with_tool(j, "hello", "Hi.")
    j.add_quality_run_sync([{"id": "a", "ok": True, "task_id": good}, {"id": "b", "ok": False, "task_id": bad}], 50.0, "BASELINE")
    grades = T.quality_grades(j)
    assert grades == {good: True, bad: False}
    assert T.grade_of(j.events(good), grades) == "pass" and T.grade_of(j.events(bad), grades) == "fail"
    assert T.grade_of(j.events(back), grades) == "sent_back" and T.grade_of(j.events(plain), grades) == "ungraded"


def test_secrets_are_skipped_whole_and_repeats_are_capped(tmp_path):
    j = Journal(tmp_path / "j.db")
    for _ in range(5):
        task_with_tool(j, "What is 17*23?", "391")
    leak = task_with_tool(j, "summarise deploy.txt", "The key is sk-live-9f8e7d6c5b4a3210 and nginx restarts.", output="api_key = 'x'")
    data = T.trajectories(j, max_per_goal=3)
    ids = {r["task_id"] for r in data["rows"]}
    assert leak not in ids and data["counts"]["skipped_secret"] == 1
    assert data["counts"]["deduped"] == 2 and data["counts"]["exported"] == 3
    assert all(r["grade"] == "ungraded" and r["tools"] == ["python_execute"] for r in data["rows"])


def test_export_writes_jsonl_in_the_workspace_and_the_cli_reports(tmp_path, monkeypatch):
    j = Journal(tmp_path / "j.db")
    task_with_tool(j, "count", "37.")
    t = j.start_task_sync("never finished")  # no final: not a trajectory
    rep = T.export(j, tmp_path / "out" / "t.jsonl", since_days=1)
    rows = [json.loads(ln) for ln in (tmp_path / "out" / "t.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rep["exported"] == 1 and len(rows) == 1 and rows[0]["messages"][-1]["content"] == "37."
    assert "backend/workspace/*" in (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert T.EXPORT_DIR == ROOT / "backend" / "workspace" / "exports"
    j.close()
    out = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: out.append(" ".join(str(x) for x in a)))
    assert T.main(["--journal", str(tmp_path / "j.db"), "--out", str(tmp_path / "cli.jsonl"), "--since", "1"]) == 0
    assert json.loads(out[0])["exported"] == 1 and (tmp_path / "cli.jsonl").is_file()
