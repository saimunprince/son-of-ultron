"""Audit 2026-11-01 (docs D2): the capability matrix counted rows merged in from the Windows journal (ids below zero)
as this PC's runtime evidence; several Linux rows were GREEN on Windows evidence alone. Only own rows count now."""

import json
import time

from syrax import capmatrix
from syrax.journal import Journal


def test_merged_rows_are_not_this_pcs_evidence(tmp_path):
    j = Journal(tmp_path / "journal.db")
    t = j.start_task_sync("play lofi")
    j.record_sync("tool.started", {"id": "a", "name": "desktop", "args": {"action": "media"}}, task_id=t)
    j.record_sync("tool.completed", {"id": "a", "name": "desktop", "ok": True, "output": "playing"}, task_id=t)
    now = time.time()
    for i, (typ, ok) in enumerate([("tool.started", None), ("tool.completed", True)] * 3):
        payload = {"id": f"w{i // 2}", "name": "youtube_play", "args": {}} if ok is None else {"id": f"w{i // 2}", "name": "youtube_play", "ok": True, "output": "x"}
        j._db.execute("INSERT INTO events (id, ts, task_id, type, payload, seq) VALUES (?, ?, NULL, ?, ?, ?)",
                      (-10_000_000 + i, now - 60, typ, json.dumps(payload), i))
    j.close()
    stats = capmatrix.read_journal(tmp_path / "journal.db")["tool_stats"]
    assert "youtube_play" not in json.dumps(stats), stats
    assert "desktop" in json.dumps(stats)
