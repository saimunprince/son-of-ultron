"""A release the guard turns down is a refusal, not the release tool failing:
SYRAX called `release` after building skills (nothing to release) and on
files outside its scope, 13 of 13 uses on 2026-10-12, and the limitation
ranking put `release` first as a broken tool. Something that really breaks
(git, the journal) is still a failure, and RISE still counts every call."""

import asyncio

from syrax import autonomy
from syrax.agent import _refused
from syrax.devloop import ReleaseTool
from syrax.journal import Journal, JournalError
from syrax.limits import recent_tool_stats

OBSERVED = "Observed output of cmd `release` executed:\n"


class Loop:
    def __init__(self, error):
        self.error = error

    async def release(self, summary, plan):
        raise self.error


def run(error):
    return asyncio.run(ReleaseTool(loop=Loop(error)).execute(summary="x")).error


def test_a_refused_plan_and_a_real_failure_read_differently():
    assert run(ValueError("nothing to release: the working tree has no changes")) == \
        "release refused: nothing to release: the working tree has no changes"
    assert run(RuntimeError("git commit failed: lock")) == "release failed: git commit failed: lock"
    assert run(JournalError("journal is read-only")) == "release failed: journal is read-only"


def test_only_guard_refusals_are_flagged():
    assert _refused("release", OBSERVED + "Error: release refused: nothing to release: the working tree has no changes")
    assert _refused("release", OBSERVED + "Error: release refused: refused: backend/app/tool/x.py: outside the self-modification scope")
    assert _refused("desktop", "Error: refused: SYSTEM is not allowed in autonomous work")
    assert not _refused("release", OBSERVED + "Error: release failed: git commit failed: lock")
    assert not _refused("python_execute", OBSERVED + "Error: release refused: copied text")  # only release's own words count


def test_the_ranking_no_longer_calls_release_broken_for_refusals(tmp_path):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("[AUTONOMOUS OBJECTIVE] build a skill", kind="autonomous")
    for i in range(3):
        j.record_sync("tool.failed", {"id": f"r{i}", "name": "release", "ok": False, "refused": True,
                                      "output": OBSERVED + "Error: release refused: nothing to release"}, task_id=t)
    j.record_sync("tool.failed", {"id": "r9", "name": "release", "ok": False, "output": OBSERVED + "Error: release failed: git"}, task_id=t)
    assert recent_tool_stats(j)["release"] == {"successes": 0, "failures": 1, "window": recent_tool_stats(j)["release"]["window"]}


def test_the_brief_says_a_skill_needs_no_release():
    assert "needs no release" in autonomy.AUTONOMOUS_BRIEF
    assert "Do not call `release`" in autonomy.BRIEF_HINTS["skill_verified"]


def test_refusals_journaled_before_the_flag_are_read_from_their_words(tmp_path):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("[AUTONOMOUS OBJECTIVE] build a skill", kind="autonomous")
    for i in range(13):  # what the live journal held: old refusals with no flag
        j.record_sync("tool.failed", {"id": f"o{i}", "name": "release", "ok": False,
                                      "output": OBSERVED + "Error: release refused: nothing to release: the working tree has no changes"}, task_id=t)
    assert "release" not in recent_tool_stats(j)  # nothing left to count: no broken release tool
    j.record_sync("tool.failed", {"id": "x", "name": "python_execute", "ok": False,
                                  "output": OBSERVED + "Error: release refused: quoted text"}, task_id=t)
    assert recent_tool_stats(j)["python_execute"]["failures"] == 1  # only release's own words count
