"""Live 2026-10-25 (audit, "Task runtime"): three INTERRUPTED tasks sat open for 3-11 days (an eval
case cut by a restart, two autonomous attempts superseded by later commits) until the owner dismissed
them by hand. SYRAX restarts itself into new code several times a day, so an interruption is routine.
The boot now settles them by a policy: kind, recovery classification and age decide; every decision is
journaled as task.cancelled with the note; a human's work waits for the human."""

import asyncio
import time

import pytest

from syrax import core as core_mod
from syrax.autonomy import derive_objectives
from syrax.core import SETTLE_CONVERSATION_S, SETTLE_UNCERTAIN_S, Core, _settle_decision
from syrax.journal import Journal
from syrax.test_bridge import TestClient, server  # noqa: F401  (the test environment: no browser, temp files)

PY = {"id": "e1", "name": "python_execute", "args": {"code": "open('r.txt', 'a').write('x')"}, "step": 2}
SHOT = {"id": "e2", "name": "desktop", "args": {"action": "screenshot"}, "step": 2}

EVAL_NOTE = "a quality case cut by a restart; the suite runs it again"
ATTEMPT_NOTE = "an autonomous attempt cut by a restart; the objective makes a fresh attempt"
UNCERTAIN_NOTE = "UNCERTAIN for 7 days, nobody resumed it; dismissed"

H = 3600.0
D = 86400.0


def dead_boot(tmp_path) -> Journal:
    """A previous process (boot_id dead-boot) that died with its tasks in flight."""
    return Journal(tmp_path / "j.db", boot_id="dead-boot", recover=False)


def seed(old: Journal, goal: str, kind: str, op: dict | None = None, ask: bool = False) -> str:
    t = old.start_task_sync(goal, kind=kind)
    old.record_sync("think", {"step": 1, "content": "working"}, task_id=t)
    if ask:
        old.record_sync("ask", {"text": "which file?"}, task_id=t)  # BLOCKED on a question
    elif op is not None:
        old.record_sync("tool.started", op, task_id=t)  # the operation recovery must verify
    return t


def boot(tmp_path) -> Journal:
    """The next boot: recovery marks the dead boot's tasks INTERRUPTED and classifies them."""
    return Journal(tmp_path / "j.db")


def aged(j: Journal, task_id: str, seconds: float) -> None:
    """The task was interrupted this long ago (recovery stamps ``updated`` when it marks the row)."""
    with j._txn() as cur:
        cur.execute("UPDATE tasks SET updated=? WHERE task_id=?", (time.time() - seconds, task_id))


def settle(core: Core, **kw) -> dict:
    return asyncio.run(core.settle_interrupted(**kw))


def ids(entries) -> set:
    return {e["task_id"] for e in entries}


def last_event(j: Journal, task_id: str) -> dict:
    return j.events(task_id)[-1]


# ——— the policy, one task of each kind / recovery / age ———


def test_each_kind_recovery_and_age_gets_its_decision_and_the_note_is_journaled(tmp_path):
    old = dead_boot(tmp_path)
    ev = seed(old, "eval: count the lines", "eval")
    a_res = seed(old, "objective A", "autonomous", op=SHOT)
    a_blk = seed(old, "objective B", "autonomous", ask=True)
    a_unc_young = seed(old, "objective C", "autonomous", op=PY)
    a_unc_old = seed(old, "objective D", "autonomous", op=PY)
    c_young = seed(old, "rename my photos", "conversation")
    c_old = seed(old, "sort the downloads", "conversation", op=SHOT)
    c_blk_old = seed(old, "book the flight", "conversation", ask=True)
    c_unc_old = seed(old, "append to the report", "conversation", op=PY)
    old.close()

    j = boot(tmp_path)
    states = {t["task_id"]: t["recovery"]["state"] for t in j.tasks(limit=50, status="INTERRUPTED")}
    assert states == {
        ev: "RESUMABLE", a_res: "RESUMABLE", a_blk: "BLOCKED", a_unc_young: "UNCERTAIN", a_unc_old: "UNCERTAIN",
        c_young: "RESUMABLE", c_old: "RESUMABLE", c_blk_old: "BLOCKED", c_unc_old: "UNCERTAIN",
    }
    aged(j, a_unc_old, SETTLE_UNCERTAIN_S + D)
    aged(j, c_old, 3 * H + 60)
    aged(j, c_blk_old, 2 * H + 60)
    aged(j, c_unc_old, 30 * D)
    core = Core(j)

    out = settle(core)

    assert ids(out["dismissed"]) == {ev, a_res, a_blk, a_unc_old, c_old, c_blk_old}
    assert ids(out["kept"]) == {a_unc_young, c_young, c_unc_old}
    notes = {d["task_id"]: d["note"] for d in out["dismissed"]}
    assert notes[ev] == EVAL_NOTE
    assert notes[a_res] == ATTEMPT_NOTE and notes[a_blk] == ATTEMPT_NOTE
    assert notes[a_unc_old] == UNCERTAIN_NOTE
    assert notes[c_old] == "interrupted 3 h ago; too old to continue safely"
    assert notes[c_blk_old] == "interrupted 2 h ago; too old to continue safely"
    for tid, note in notes.items():
        row = j.task(tid)
        assert row["status"] == "CANCELLED" and row["error"] == note, row
        e = last_event(j, tid)
        assert e["type"] == "task.cancelled" and e["payload"] == {"error": note}
    for tid in (a_unc_young, c_young, c_unc_old):
        assert j.task(tid)["status"] == "INTERRUPTED"
        assert last_event(j, tid)["type"] == "task.interrupted"
    kinds = {k["task_id"]: (k["kind"], k["recovery_state"]) for k in out["kept"]}
    assert kinds == {a_unc_young: ("autonomous", "UNCERTAIN"), c_young: ("conversation", "RESUMABLE"),
                     c_unc_old: ("conversation", "UNCERTAIN")}
    # the kept ones are still offered to the human on (re)connect; the dismissed ones are gone
    assert ids(core.snapshot()["interrupted"]) == {a_unc_young, c_young, c_unc_old}
    # a second boot finds nothing new to dismiss and keeps the same ones
    again = settle(core)
    assert again["dismissed"] == [] and ids(again["kept"]) == {a_unc_young, c_young, c_unc_old}
    j.close()


def test_a_young_conversation_is_dismissed_once_it_is_an_hour_old(tmp_path):
    old = dead_boot(tmp_path)
    t = seed(old, "rename my photos", "conversation")
    old.close()
    j = boot(tmp_path)
    core = Core(j)
    now = time.time()
    assert ids(settle(core, now=now + SETTLE_CONVERSATION_S - 60)["kept"]) == {t}
    assert j.task(t)["status"] == "INTERRUPTED"
    out = settle(core, now=now + SETTLE_CONVERSATION_S + 60)
    assert ids(out["dismissed"]) == {t} and out["dismissed"][0]["note"] == "interrupted 1 h ago; too old to continue safely"
    assert j.task(t)["status"] == "CANCELLED"
    j.close()


# ——— objectives: nothing is left pointing at a dismissed attempt ———


def test_a_dismissed_autonomous_attempt_reopens_the_objective_still_active_for_it(tmp_path):
    old = dead_boot(tmp_path)
    t = seed(old, "Brain latency: three steps, one release.", "autonomous", op=SHOT)
    old.close()
    j = boot(tmp_path)
    core = Core(j)  # Autonomy's own recover_active runs here, before any objective is ACTIVE
    by_goal = j.add_objective_sync("Brain latency: three steps, one release.", "test", 2, "human", {"kind": "change_released"})
    by_task = j.add_objective_sync("another goal, an earlier attempt of it was this task", "test", 2, "human")
    other = j.add_objective_sync("unrelated work", "test", 3, "human")
    # the cycle marks ACTIVE without last_task_id (it sets that only when the task ends)
    j.update_objective_sync(by_goal["id"], status="ACTIVE", note="cycle picked this objective")
    j.update_objective_sync(by_task["id"], status="ACTIVE", last_task_id=t, note="cycle picked this objective")
    j.update_objective_sync(other["id"], status="ACTIVE", note="cycle picked this objective")

    out = settle(core)

    assert ids(out["dismissed"]) == {t} and j.task(t)["status"] == "CANCELLED"
    for o in (by_goal, by_task):
        row = j.objective(o["id"])
        assert row["status"] == "OPEN", row
        ev = [e for e in j.recent_events(limit=50) if e["type"] == "objective.updated" and e["payload"]["objective_id"] == o["id"]][-1]
        assert ev["payload"]["note"] == f"task {t} dismissed at boot: {ATTEMPT_NOTE}"
    assert j.objective(other["id"])["status"] == "ACTIVE"  # not this task's: the boot policy does not touch it
    j.close()


def test_an_uncertain_attempt_waits_a_week_for_the_human_then_its_objective_is_dropped_with_it(tmp_path):
    old = dead_boot(tmp_path)
    young = seed(old, "objective Y", "autonomous", op=PY)
    stale = seed(old, "objective Z", "autonomous", op=PY)
    old.close()
    j = boot(tmp_path)
    aged(j, stale, SETTLE_UNCERTAIN_S + D)
    core = Core(j)
    # autonomy still asks a human about every UNCERTAIN interruption (autonomy.derive_objectives)
    derive_objectives(j, core.selfmodel)
    asks = {o["key"]: o for o in j.objectives(limit=500) if (o.get("key") or "").startswith("uncertain-task:")}
    assert set(asks) == {f"uncertain-task:{young}", f"uncertain-task:{stale}"}
    assert all(o["status"] == "BLOCKED" and o["check_spec"] == {"kind": "human"} for o in asks.values())

    out = settle(core)

    assert ids(out["dismissed"]) == {stale} and out["dismissed"][0]["note"] == UNCERTAIN_NOTE
    assert ids(out["kept"]) == {young}
    assert j.task(stale)["status"] == "CANCELLED" and j.task(stale)["error"] == UNCERTAIN_NOTE
    dropped = j.objective(asks[f"uncertain-task:{stale}"]["id"])
    assert dropped["status"] == "DROPPED"
    drop_ev = [e for e in j.recent_events(limit=50) if e["type"] == "objective.dropped"][-1]
    assert drop_ev["payload"]["objective_id"] == dropped["id"]
    assert drop_ev["payload"]["note"] == f"task {stale} dismissed at boot: {UNCERTAIN_NOTE}"
    assert j.task(young)["status"] == "INTERRUPTED"
    assert j.objective(asks[f"uncertain-task:{young}"]["id"])["status"] == "BLOCKED"  # still asking
    assert ids(core.snapshot()["interrupted"]) == {young}
    j.close()


# ——— the table itself ———


@pytest.mark.parametrize(
    "kind,state,age_s,expected",
    [
        ("eval", "RESUMABLE", 0, (EVAL_NOTE, False)),
        ("eval", "UNCERTAIN", 0, (EVAL_NOTE, False)),
        ("autonomous", "RESUMABLE", 0, (ATTEMPT_NOTE, False)),
        ("autonomous", "BLOCKED", 0, (ATTEMPT_NOTE, False)),
        ("autonomous", "UNCERTAIN", 6 * D, None),
        ("autonomous", "UNCERTAIN", 7 * D, (UNCERTAIN_NOTE, True)),
        ("conversation", "RESUMABLE", 59 * 60, None),
        ("conversation", "BLOCKED", 59 * 60, None),
        ("conversation", "RESUMABLE", 5 * H, ("interrupted 5 h ago; too old to continue safely", False)),
        ("conversation", "BLOCKED", 1 * H, ("interrupted 1 h ago; too old to continue safely", False)),
        ("conversation", "UNCERTAIN", 400 * D, None),
        ("reminder", "RESUMABLE", 400 * D, None),  # an unknown kind is nobody's to dismiss
    ],
)
def test_the_boot_policy_table(kind, state, age_s, expected):
    now = 1_800_000_000.0
    t = {"task_id": "t1", "kind": kind, "recovery": {"state": state}, "updated": now - age_s, "created": now - age_s - 10}
    assert _settle_decision(t, now) == expected


# ——— the server boot runs it, after auto_resume and before the queue restarts ———


def test_the_server_boot_settles_after_auto_resume_and_before_the_queue(monkeypatch):
    calls = []

    async def auto_resume(self):
        calls.append("auto_resume")
        return []

    async def settle_interrupted(self, now=None):
        calls.append("settle_interrupted")
        return {"dismissed": [], "kept": []}

    async def requeue_after_boot(self):
        calls.append("requeue_after_boot")
        return {"kept": [], "dropped": [], "started": None}

    monkeypatch.setattr(core_mod.Core, "auto_resume", auto_resume)
    monkeypatch.setattr(core_mod.Core, "settle_interrupted", settle_interrupted)
    monkeypatch.setattr(core_mod.Core, "requeue_after_boot", requeue_after_boot)
    with TestClient(server.app):
        pass
    assert calls == ["auto_resume", "settle_interrupted", "requeue_after_boot"]
