"""EVOLUTION_PLAN wave 4 (directions 91 skill extraction, 92 workflow synthesis, 95 tool composition): a repeated request
became a skill proposal that named only the tools used. The proposal now carries the workflow: the ordered tool calls
the tasks shared, with the arguments that differed turned into parameters, so the skill is built from the real steps."""

from syrax import skillevo
from syrax.journal import Journal


def task(j, goal, steps):
    t = j.start_task_sync(goal)
    for i, (name, args) in enumerate(steps):
        j.record_sync("tool.started", {"id": f"c{i}", "name": name, "args": args}, task_id=t)
        j.record_sync("tool.completed", {"id": f"c{i}", "name": name, "ok": True, "output": "ok"}, task_id=t)
    j.record_sync("final", {"text": "done"}, task_id=t)
    j.record_sync("task.completed", {"status": "SUCCESS"}, task_id=t)
    return t


def test_the_shared_sequence_becomes_a_parameterized_workflow(tmp_path):
    j = Journal(tmp_path / "j.db")
    ids = [task(j, f"weather report for {c} please", [("research", {"query": f"weather {c}", "depth": 1}),
                                                   ("python_execute", {"code": "print('formatted')"})])
           for c in ("Dhaka", "Paris", "Tokyo")]
    w = skillevo.workflow_of(j, ids)
    assert [s["tool"] for s in w["steps"]] == ["research", "python_execute"]
    assert w["steps"][0]["args"] == {"depth": 1, "query": "{p1}"} and w["steps"][1]["args"]["code"] == "print('formatted')"
    assert w["params"][0]["examples"] == ["weather Dhaka", "weather Paris", "weather Tokyo"] and w["support"] == 3
    assert skillevo.render_workflow(w) == "1. research(depth=1, query={p1}) 2. python_execute(code=print('formatted'))"


def test_no_shared_shape_no_workflow(tmp_path):
    j = Journal(tmp_path / "j.db")
    ids = [task(j, "a", [("research", {"q": 1})]), task(j, "b", [("weather", {"c": 2})]), task(j, "c", [("pdf_text", {})])]
    assert skillevo.workflow_of(j, ids) is None


def test_the_proposal_carries_the_steps(tmp_path):
    j = Journal(tmp_path / "j.db")
    for c in ("Dhaka", "Paris", "Tokyo"):
        task(j, f"weather report for {c} please", [("research", {"query": f"weather {c}"})])
    assert skillevo.propose_candidates(j) == 1
    prop = [e["payload"] for e in j.recent_events(80) if e["type"] == "proposal.created"][-1]
    assert "The steps it would wrap: 1. research(query={p1})" in prop["proposal"] and prop["workflow"]["support"] == 3
