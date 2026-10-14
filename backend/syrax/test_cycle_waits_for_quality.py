"""Between two quality cases the core is idle for a moment. The autonomy cycle
must not take that moment: an objective task would make the next case fail
"core busy", and a self-restart would end the run. A quality run (or a brain
comparison, across both of its runs) counts as busy for the cycle."""

import asyncio

from syrax.quality import QualityRunner
from syrax.test_autonomy import make


def test_the_cycle_waits_while_a_quality_run_is_measuring(tmp_path):
    j, core, a = make(tmp_path, tools=["terminate"])
    a.set_enabled(True)
    core.quality = type("Q", (), {"running": True})()
    rep = asyncio.run(a.run_once())
    assert rep.outcome == "BUSY" and rep.reason == "a quality run is measuring"
    core.quality.running = False
    assert asyncio.run(a.run_once()).outcome != "BUSY"


def test_the_runner_says_it_is_running_for_the_whole_run_and_a_comparison(tmp_path):
    from syrax.journal import Journal

    j = Journal(tmp_path / "j.db")
    seen = []

    class Core:
        journal, busy, agent = j, False, None

        async def submit(self, goal, said, session_id, kind="conversation"):
            seen.append(runner.running)
            t = j.start_task_sync(said or goal, kind=kind)
            j.record_sync("final", {"text": "391"}, task_id=t)
            j.record_sync("task.completed", {"status": "SUCCESS", "result": "391"}, task_id=t)
            return t

        async def wait(self):
            seen.append(runner.running)

    runner = QualityRunner(Core(), j, workspace=tmp_path / "ws", case_timeout=5)
    case = {"id": "arith", "prompt": "17*23?", "checks": [{"kind": "final_regex", "pattern": "391"}]}
    asyncio.run(runner.run(cases=[case, dict(case, id="arith2")]))
    assert seen and all(seen) and runner.running is False
