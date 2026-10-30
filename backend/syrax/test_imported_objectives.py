"""Live 2026-10-30: objectives merged in from the Windows journal (ids shifted below zero) were reopened by
catalog.reopen_regressed (their skills are not on this PC) and pursued by this PC's autonomy, beside its own copies of
the same features: three attempts each, then BLOCKED. A merged objective is the other PC's history: it is never
reopened, re-judged or picked here."""

from syrax import catalog
from syrax.autonomy import rejudge_blocked
from syrax.test_autonomy import make


def merged(j, status, key, check):
    o = j.add_objective_sync(f"merged {key}", None, 1, "human", check, key=key)
    j._db.execute("UPDATE objectives SET id=?, status=? WHERE id=?", (-10_000_000 + o["id"], status, o["id"]))
    return -10_000_000 + o["id"]


def test_merged_objectives_are_never_picked_reopened_or_rejudged(tmp_path):
    j, core, a = make(tmp_path)
    open_id = merged(j, "OPEN", "k-open", {"kind": "tool_verified", "tool": "desktop"})
    done_id = merged(j, "DONE", "feature:image_tools", {"kind": "skill_verified", "name": "image_tools"})
    blocked_id = merged(j, "BLOCKED", "k-blocked", {"kind": "tool_verified", "tool": "terminate"})
    own = j.add_objective_sync("own work", None, 2, "human", {"kind": "tool_verified", "tool": "self_inspect"})
    assert a._pick()["id"] == own["id"]  # the merged OPEN one (priority 1) is skipped
    assert done_id not in catalog.reopen_regressed(j)  # its skill is missing here, and it stays DONE
    assert j.objective(done_id)["status"] == "DONE"
    rejudge_blocked(j)
    assert j.objective(blocked_id)["status"] == "BLOCKED" and j.objective(open_id)["status"] == "OPEN"


def test_the_feature_goal_says_a_direct_call_is_needed():
    f = next(x for x in catalog.CATALOG if x.check and x.check.get("kind") == "skill_verified")
    goal = catalog.goal_of(f)
    assert "one direct call of the tool" in goal and "not python_execute" in goal
