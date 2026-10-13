"""The tool-reliability judge counts the newest uses after its objective, not
the first 10 000 events after it: an old objective would otherwise never see
the uses that fix it. Refused calls are not the tool failing."""

import time

from syrax import limits
from syrax.journal import Journal


def test_new_uses_count_however_much_happened_since_the_objective(tmp_path):
    j = Journal(tmp_path / "j.db")
    obj = j.add_objective_sync("make the editor reliable", None, 3, "selfmodel", {"kind": "tool_reliability", "tool": "str_replace_editor", "min_uses": 5, "max_rate": 0.1})
    t = j.start_task_sync("busy day")
    for i in range(10050):  # a long day of other work after the objective
        j.record_sync("think", {"step": i}, task_id=t)
    for i in range(6):
        j.record_sync("tool.completed", {"id": f"e{i}", "name": "str_replace_editor", "ok": True}, task_id=t)
    j.record_sync("tool.failed", {"id": "r", "name": "str_replace_editor", "ok": False, "refused": True,
                                  "output": "Error: refused: outside the scope"}, task_id=t)
    verdict, ev = limits.judge_tool_reliability(j, obj)
    assert verdict == "DONE" and ev["uses_since"] == 6 and ev["failures_since"] == 0
