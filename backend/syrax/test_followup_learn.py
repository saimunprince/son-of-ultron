"""Live 2026-10-15: a blocked learning objective drew its own learning
objective, "Learn how to do what objective #239 could not: Learn how to do
what objective #238 could not: Self-model: GPU is not probed". Learning how
to learn changes nothing; a learning objective gets no follow-up, and the
retry that waited for it is dropped instead of waiting forever."""

import asyncio

from syrax import followup
from syrax.journal import Journal
from syrax.test_autonomy import make, use_tool


def test_a_blocked_learning_objective_gets_no_learning_objective(tmp_path):
    j = Journal(tmp_path / "j.db")
    topic = "Self-model: GPU is not probed"
    o = j.add_objective_sync(f"Learn how to do what objective #238 could not: {topic}.", source="followup",
                             check={"kind": "knowledge_stored", "topic": topic}, key="followup:238:learn",
                             evidence={"followup_of": 238, "followup_depth": 1})
    t = j.start_task_sync("attempt", kind="autonomous")
    use_tool("research", ok=False)(t, j)
    j.update_objective_sync(o["id"], status="BLOCKED", last_task_id=t, progress={"attempts_log": [{"task_id": t, "lesson": "research failed"}]})
    blocked = [x for x in j.objectives(limit=10) if x["id"] == o["id"]][0]
    assert followup.derive(j, blocked) == []
    assert not [x for x in j.objectives(limit=10) if x["source"] == "followup" and x["id"] != o["id"]]


def test_the_retry_waiting_for_a_blocked_learning_objective_is_dropped(tmp_path, monkeypatch):
    j, core, a = make(tmp_path)
    monkeypatch.setattr("syrax.autonomy.resource_pressure", lambda: None)
    learn = j.add_objective_sync("Learn how to probe an AMD GPU", source="followup", check={"kind": "knowledge_stored", "topic": "AMD GPU probe"},
                                 key="followup:238:learn", priority=1, evidence={"followup_of": 238, "followup_depth": 1})
    retry = j.add_objective_sync("Probe the GPU", source="followup", check={"kind": "tool_verified", "tool": "desktop"},
                                 key="followup:238:retry", priority=1, dependencies=[learn["id"]])
    core.script = [lambda t: "found nothing", lambda t: "found nothing", lambda t: "found nothing"]
    for _ in range(3):
        if j.objective(learn["id"])["status"] == "BLOCKED":
            break
        asyncio.run(a.run_once(force=True))
    assert j.objective(learn["id"])["status"] == "BLOCKED"
    assert j.objective(retry["id"])["status"] == "DROPPED"
    assert followup.drop_dependents(j, learn["id"]) == []  # nothing left waiting
