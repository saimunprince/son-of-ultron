"""Phase 3: skills evolve from real use; repeated requests are proposed as skills."""

import asyncio

from syrax import limits, plan, skillevo
from syrax.journal import Journal
from syrax.test_limits import FakeSelf
from syrax.test_skills import GOOD, GOOD_TEST, factory


def verified_word_count(tmp_path):
    j, f, coll = factory(tmp_path)
    assert asyncio.run(f.create("word_count", "count words", GOOD, GOOD_TEST))["status"] == "VERIFIED"
    return j, f


def use(j, name, ok, n, out="boom"):
    t = j.start_task_sync("use it")
    for i in range(n):
        j.record_sync("tool.started", {"id": f"{name}{ok}{i}", "name": name, "args": {}}, task_id=t)
        j.record_sync("tool.completed" if ok else "tool.failed", {"id": f"{name}{ok}{i}", "name": name, "ok": ok, "output": out}, task_id=t)
    j.record_sync("final", {"text": "x"}, task_id=t)
    j.record_sync("task.completed", {"status": "SUCCESS", "result": "x"}, task_id=t)
    return t


def test_real_use_is_counted_per_skill_and_shown_in_the_list(tmp_path):
    j, f = verified_word_count(tmp_path)
    use(j, "word_count", True, 3)
    t = use(j, "word_count", False, 1, "Error: unicode text")
    st = skillevo.real_use(j)["word_count"]
    assert (st["uses"], st["failures"]) == (4, 1) and st["recent_failures"][0]["task_id"] == t
    assert f.list()[0]["real_use"] == {"uses": 4, "failures": 1, "since": st["since"], "version": 1}


def test_a_skill_failing_in_real_use_ranks_as_a_repair_not_a_code_fix(tmp_path):
    j, f = verified_word_count(tmp_path)
    use(j, "word_count", True, 3)
    use(j, "word_count", False, 4, "Error: unicode text")
    ranked = limits.rank(j, FakeSelf())
    kinds = {(r["kind"], r["subject"]) for r in ranked}
    assert ("skill_repair", "word_count") in kinds and ("tool_reliability", "word_count") not in kinds
    rep = [r for r in ranked if r["kind"] == "skill_repair"][0]
    assert rep["check"] == {"kind": "skill_verified", "name": "word_count"} and "4 of 7" in rep["detail"]
    assert len(rep["plan"]) == len(rep["plan_checks"]) and rep["evidence"]["recent_failures"][0]["output"].endswith("unicode text")
    chosen = limits.choose(j, FakeSelf())
    o = j.objective(chosen["objective_id"])
    assert plan.steps_of(o)[3]["check"] == {"kind": "tool_ok", "tools": ["word_count"]}


def test_a_skill_doing_fine_is_left_alone(tmp_path):
    j, f = verified_word_count(tmp_path)
    use(j, "word_count", True, 9)
    use(j, "word_count", False, 1)
    assert skillevo.repairs(j) == []


def request(j, goal, tools=("python_execute",), kind="conversation"):
    t = j.start_task_sync(goal, kind=kind)
    for n in tools:
        j.record_sync("tool.started", {"id": n, "name": n, "args": {}}, task_id=t)
        j.record_sync("tool.completed", {"id": n, "name": n, "ok": True, "output": "ok"}, task_id=t)
    j.record_sync("final", {"text": "x"}, task_id=t)
    j.record_sync("task.completed", {"status": "SUCCESS", "result": "x"}, task_id=t)
    return t


def test_a_request_repeated_three_times_becomes_one_skill_proposal(tmp_path):
    j = Journal(tmp_path / "j.db")
    request(j, "convert invoice.csv to an excel sheet")
    request(j, "convert orders.csv to an excel sheet")
    request(j, "convert stock.csv to an excel sheet")
    request(j, "what is the weather in dhaka")  # different
    request(j, "convert stock csv to excel sheet", kind="autonomous")  # SYRAX's own work does not count
    c = skillevo.candidates(j)
    assert len(c) == 1 and len(c[0]["tasks"]) == 3 and {"convert", "excel", "sheet"} <= set(c[0]["key"].split())
    assert skillevo.propose_candidates(j) == 1 and skillevo.propose_candidates(j) == 0  # once
    prop = [e for e in j.recent_events(200) if e["type"] == "proposal.created"][-1]["payload"]
    assert prop["kind"] == "skill_candidate" and "3 times" in prop["proposal"] and len(prop["tasks"]) == 3


def test_requests_already_served_by_a_skill_or_with_no_real_tools_are_not_candidates(tmp_path):
    j, f = verified_word_count(tmp_path)
    for _ in range(3):
        request(j, "count the words in my essay draft", tools=("word_count",))
        request(j, "tell me about my essay draft today", tools=("self_inspect",))
    assert skillevo.candidates(j) == []
