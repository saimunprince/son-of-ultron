"""The matrix rows added 2026-10-12 read real evidence: the phase model counts
the latest SUCCESS tasks whose phases (recomputed from their events, as the
UI does) reach verify; live talk counts closed sessions; click-by-sight
counts click_text/find_text calls. STT maps the tests that run."""

import time

from syrax import capmatrix as cm
from syrax.journal import Journal


def seeded(tmp_path):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("what is 2+2")
    j.record_sync("think", {"step": 1, "content": "4", "tools": []}, task_id=t)
    j.record_sync("final", {"text": "4"}, task_id=t)
    j.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t)
    u = j.start_task_sync("click Save")
    j.record_sync("think", {"step": 1, "tools": [{"name": "desktop"}]}, task_id=u)
    j.record_sync("tool.started", {"id": "s1", "name": "desktop", "args": {"action": "click_text", "target": "Save"}, "step": 1}, task_id=u)
    j.record_sync("tool.completed", {"id": "s1", "name": "desktop", "ok": True, "output": "Left-clicked at 1,2."}, task_id=u)
    j.record_sync("live.opened", {"model": "m", "session": "s"})
    j.record_sync("live.closed", {"model": "m", "session": "s", "seconds": 9, "tasks": 0, "reason": "the human ended it"})
    j.close()
    return tmp_path / "j.db"


def test_the_new_rows_read_their_evidence_from_the_journal(tmp_path):
    journal = cm.read_journal(seeded(tmp_path), time.time())
    assert journal["phases"] == {"tasks": 1, "verified": 1}  # the click task never finished
    assert journal["counts"]["live_sessions"] == 1 and journal["counts"]["sight_used"] == 1
    live = cm.live_checks(None, None, journal)
    assert live["phases"] == ("pass", "1 of the last 1 SUCCESS tasks reached verify (phases from their events)")
    assert live["live_sessions"][0] == "pass" and live["sight_used"][0] == "pass"


def test_the_spec_names_the_rows_and_stt_maps_tests_that_run():
    caps = {c.id: c for c in cm.CAPABILITIES}
    assert caps["phases"].implementation == cm.CURRENT and caps["phases"].live == ["phases"]
    assert {"live_voice", "sight"} <= set(caps)
    assert caps["voice_in"].tests == ["syrax.test_voice::test_stt_*"]
