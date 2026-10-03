"""Tool-reliability objectives count only uses recorded after they were
created, by event order, not by clock (Windows time.time() ticks ~15 ms)."""

from syrax import limits
from syrax.journal import Journal
from syrax.test_limits import FakeSelf, use


def test_uses_in_the_same_clock_tick_as_the_objective_do_not_count(tmp_path, monkeypatch):
    import syrax.journal as jm
    frozen = jm._now()
    monkeypatch.setattr(jm, "_now", lambda: frozen)  # every event and the objective share one timestamp
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("work")
    use(j, t, "str_replace_editor", False, 10)
    use(j, t, "str_replace_editor", True, 10)
    o = limits.choose(j, FakeSelf())
    obj = [x for x in j.objectives() if x["id"] == o["objective_id"]][0]
    verdict, ev = limits.judge_tool_reliability(j, obj)
    assert verdict == "RETRY" and ev["uses_since"] == 0
    use(j, j.start_task_sync("after"), "str_replace_editor", True, 5)
    verdict, ev = limits.judge_tool_reliability(j, obj)
    assert verdict == "DONE" and ev["uses_since"] == 5
