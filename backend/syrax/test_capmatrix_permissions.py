"""The permissions row is GREEN only once the gate has both authorized and
refused something at runtime; a gate that never refused is not proven."""

import time

from syrax import capmatrix as cm
from syrax.journal import Journal


def _journal(tmp_path, refused: bool):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("delete the file x.txt")
    j.record_sync("permission.authorized", {"tool": "python_execute", "level": "DESTRUCTIVE", "task_kind": "conversation", "authorized_by": "goal"}, task_id=t)
    if refused:
        j.record_sync("permission.refused", {"tool": "python_execute", "level": "DESTRUCTIVE", "task_kind": "autonomous", "authorized_by": "policy"}, task_id=t)
    j.record_sync("final", {"text": "done"}, task_id=t)
    j.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t)
    j.close()
    return tmp_path / "j.db"


def test_permissions_live_check_needs_both_outcomes(tmp_path):
    now = time.time()
    journal = cm.read_journal(_journal(tmp_path, refused=False), now)
    assert cm.live_checks(None, None, journal)["permissions"][0] is None
    journal = cm.read_journal(_journal(tmp_path / "b", refused=True), now)
    result, detail = cm.live_checks(None, None, journal)["permissions"]
    assert result == "pass" and "1 authorized / 1 refused" in detail


def test_permissions_row_is_current_and_mapped():
    row = next(c for c in cm.CAPABILITIES if c.id == "permissions")
    assert row.implementation == cm.CURRENT
    assert row.tests == ["syrax.test_permissions*::*"] and row.live == ["permissions"]
