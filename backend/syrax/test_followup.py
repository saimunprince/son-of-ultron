"""Phase 1: a blocked objective's evidence decides the next objective."""

import asyncio

from syrax import followup
from syrax.test_autonomy import make, use_tool


def _blocked(j, o):
    return [x for x in j.objectives(limit=50) if x["id"] == o["id"]][0]


def test_blocked_without_knowing_how_learns_first_then_retries_with_what_it_learned(tmp_path, monkeypatch):
    j, core, a = make(tmp_path)
    monkeypatch.setattr("syrax.autonomy.resource_pressure", lambda: None)
    same = lambda t: (use_tool("python_execute", ok=False)(t, j), "tried python")[1]
    core.script = [same, same]
    o = j.add_objective_sync("make desktop screenshots work", source="selfmodel", check={"kind": "tool_verified", "tool": "desktop"}, key="d",
                             evidence={"plan": ["Use desktop screenshot."], "plan_checks": [{"kind": "tool_ok", "tools": ["desktop"]}]})
    asyncio.run(a.run_once(force=True))
    assert asyncio.run(a.run_once(force=True)).verdict == "BLOCKED"
    kids = [x for x in j.objectives(limit=50) if x["source"] == "followup"]
    learn = [x for x in kids if x["check_spec"]["kind"] == "knowledge_stored"][0]
    retry = [x for x in kids if x["check_spec"] == {"kind": "tool_verified", "tool": "desktop"}][0]
    assert learn["evidence"]["followup_of"] == o["id"] and "make desktop screenshots work" in learn["goal"]
    assert retry["dependencies"] == [learn["id"]] and retry["goal"] == o["goal"] and retry["evidence"]["plan"] == ["Use desktop screenshot."]
    assert a._pick()["id"] == learn["id"]  # the retry waits for the learning
    assert followup.derive(j, _blocked(j, o)) == []  # once per blocked objective
    ev = [e for e in j.recent_events(500) if e["type"] == "followup.derived"][-1]["payload"]
    assert ev["objective_id"] == o["id"] and set(ev["created"]) == {learn["id"], retry["id"]}

    # the learning objective closes on stored knowledge; the retry is briefed with it
    def research(t):
        use_tool("research")(t, j)
        j.add_knowledge_sync("make desktop screenshots work on Windows with PIL ImageGrab", "web", source_url="http://pil", tags=["desktop", "screenshots"], task_id=t)
        return "learned"
    core.script = [research, lambda t: "ok"]
    assert asyncio.run(a.run_once(force=True)).verdict == "DONE"
    asyncio.run(a.run_once(force=True))
    assert core.submitted[-1][1].count("PIL ImageGrab") == 1 and f"What objective #{learn['id']} learned" in core.submitted[-1][1]


def test_released_but_still_failing_asks_for_the_cause_the_fix_missed(tmp_path):
    from syrax.journal import Journal
    j = Journal(tmp_path / "j.db")
    o = j.add_objective_sync("fix editor failures", source="selfmodel", key="e",
                             check={"kind": "tool_reliability", "tool": "str_replace_editor", "max_rate": 0.1, "min_uses": 3},
                             evidence={"limitation": {"kind": "tool_reliability", "detail": "editor fails"}, "plan": ["a", "b"], "plan_checks": [None, None]})
    t = j.start_task_sync("attempt", kind="autonomous")
    j.record_sync("commit.created", {"commit": "abc1234def"}, task_id=t)
    use_tool("str_replace_editor", ok=False)(t, j)
    j.update_objective_sync(o["id"], status="BLOCKED", last_task_id=t, progress={"attempts_log": [{"task_id": t, "lesson": "rate still 40 %"}]})
    kids = followup.derive(j, _blocked(j, o))
    assert len(kids) == 1
    k = kids[0]
    assert "abc1234" in k["goal"] and k["check_spec"] == o["check_spec"] and k["evidence"]["released"] == ["abc1234"]
    assert k["evidence"]["failures_after_release"][0]["task_id"] == t and k["evidence"]["lessons"] == ["rate still 40 %"]
    assert k["evidence"]["limitation"]["kind"] == "tool_reliability"


def test_follow_ups_stop_at_max_depth_and_never_for_human_checks(tmp_path):
    from syrax.journal import Journal
    j = Journal(tmp_path / "j.db")
    deep = j.add_objective_sync("x", source="followup", check={"kind": "tool_verified", "tool": "t"}, key="x",
                                evidence={"followup_depth": followup.MAX_DEPTH})
    human = j.add_objective_sync("y", check={"kind": "human"}, key="y")
    assert followup.derive(j, deep) == [] and followup.derive(j, human) == []
