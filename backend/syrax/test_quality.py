"""Task-quality benchmark: checks are evidence-only; regressions are pass-rate drops."""

from syrax.journal import Journal
from syrax.quality import _cases, check_case, format_report


def test_check_case_uses_final_tools_and_files(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    cases = {c["id"]: c for c in _cases(ws)}
    env = {"git_short": "abc1234", "cpu_count": "16"}
    ok_task = {"status": "SUCCESS", "result": "The answer is 391."}
    events = []
    res = check_case(cases["arith"], ok_task, events, env)
    assert all(c["ok"] for c in res)
    res = check_case(cases["arith"], {"status": "SUCCESS", "result": "about 390"}, events, env)
    assert not res[0]["ok"] and "390" in res[0]["detail"]
    used = [{"type": "tool.started", "payload": {"name": "python_execute"}}, {"type": "tool.started", "payload": {"name": "terminate"}}]
    res = check_case(cases["python"], {"status": "SUCCESS", "result": "6765"}, used, env)
    assert all(c["ok"] for c in res)
    res = check_case(cases["python"], {"status": "SUCCESS", "result": "6765"}, [], env)
    assert res[0]["ok"] is False and "tools: []" in res[0]["detail"] and res[1]["ok"]
    res = check_case(cases["restraint"], {"status": "SUCCESS", "result": "Ready."}, [], env)
    assert all(c["ok"] for c in res)
    res = check_case(cases["restraint"], {"status": "SUCCESS", "result": "Ready."}, used, env)
    assert res[0]["ok"] is False
    (ws / "hello.txt").write_text("HELLO SYRAX")
    assert check_case(cases["file_create"], ok_task, [], env)[0]["ok"]
    (ws / "hello.txt").write_text("hello syrax\n")
    assert not check_case(cases["file_create"], ok_task, [], env)[0]["ok"]
    res = check_case(cases["self_version"], {"status": "SUCCESS", "result": "abc1234"}, [{"type": "tool.started", "payload": {"name": "self_inspect"}}], env)
    assert all(c["ok"] for c in res)
    res = check_case(cases["desktop_cpu"], {"status": "SUCCESS", "result": "16 cores"}, [{"type": "tool.started", "payload": {"name": "desktop"}}], env)
    assert all(c["ok"] for c in res)
    res = check_case(cases["arith"], {"status": "FAILED", "result": None, "error": "boom"}, [], env)
    assert res[-1]["check"] == "task SUCCESS" and not res[-1]["ok"]


def test_quality_runs_table_and_report(tmp_path):
    j = Journal(tmp_path / "j.db")
    results = [{"id": "arith", "ok": True, "steps": 1, "ms": 900, "checks": []}, {"id": "python", "ok": False, "steps": 3, "ms": 4000, "checks": [{"check": "final matches 6765", "ok": False, "detail": "6766"}]}]
    row = j.add_quality_run_sync(results, 50.0, "BASELINE", brain="pollinations")
    assert row["status"] == "BASELINE" and row["pass_rate"] == 50.0 and row["git_head"]
    row2 = j.add_quality_run_sync(results, 30.0, "REGRESSION", compared_to=row["id"], delta=-20.0, brain="pollinations")
    assert [r["status"] for r in j.quality_runs()] == ["REGRESSION", "BASELINE"]
    ev = j.recent_events()[-1]
    assert ev["type"] == "quality.completed" and ev["payload"]["failed"] == ["python"] and ev["payload"]["delta"] == -20.0
    text = format_report(row2)
    assert text.startswith("QUALITY REGRESSION · 30.0% pass (1/2) · vs #1 -20.0 pp · brain pollinations")
    assert "FAIL python" in text and "✕ final matches 6765: 6766" in text


def test_recent_exchanges_come_from_the_journal_and_history_file_is_fallback(tmp_path, monkeypatch):
    import syrax.journal as journal_mod
    from syrax.memory import MemoryStore

    m = MemoryStore(tmp_path / "memory.json", tmp_path / "history.jsonl")
    m.add_exchange("old question", "old answer")
    j = Journal(tmp_path / "j.db")
    monkeypatch.setattr(journal_mod, "_journal", j)
    assert m.recent()[-1]["user"] == "old question"  # journal empty → legacy file
    t = j.start_task_sync("what is my colour?")
    j.record_sync("final", {"text": "Crimson."}, task_id=t)
    j.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t)
    a = j.start_task_sync("autonomous thing", kind="autonomous")
    j.record_sync("final", {"text": "done"}, task_id=a)
    j.record_sync("task.completed", {"status": "SUCCESS"}, task_id=a)
    f = j.start_task_sync("failed one")
    j.record_sync("task.failed", {"error": "x"}, task_id=f)
    rec = m.recent()
    assert [r["user"] for r in rec] == ["what is my colour?"] and rec[0]["reply"] == "Crimson."
    assert "what is my colour?" in m.prompt_block() and "old question" not in m.prompt_block()
    assert j.recent_exchanges(1)[0]["user"] == "what is my colour?"
