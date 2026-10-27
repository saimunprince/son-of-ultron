"""Settle objectives and knowledge evidence follow the rows' own state (fix-settle, 2026-10-27).

Before: autonomy derived "my knowledge contradicts itself" objectives from the last 2000 events, so an older dispute
(still DISPUTED on its rows) got no objective, and a pair already settled got one anyway; the objective closed on any
stored or reinforced row about the topic, even with both rows still DISPUTED. contracts and followup read cited rows
by id without their status, so a SUPERSEDED (replaced) or DISPUTED (contradicted) row counted as what was learned.
Now the derivation reads the DISPUTED rows, the objective closes only when none of its rows is DISPUTED, and only an
ACTIVE row is evidence."""

import asyncio
import time

from syrax import contracts, followup
from syrax.autonomy import derive_objectives, judge
from syrax.journal import Journal
from syrax.research import LearnTool
from syrax.selfmodel import SelfModel


def web(j, text, url, task_id=None):
    return j.add_knowledge_sync(text, "web", source_url=url, excerpt=text, tags=["sqlite"], task_id=task_id)["id"]


def learn(j, claim, *sources, task_id=None):
    return asyncio.run(LearnTool(journal=j, task_id_provider=lambda: task_id).execute(claim=claim, sources=list(sources))).output


def disputed_pair(tmp_path):
    j = Journal(tmp_path / "j.db")
    src = web(j, "SQLite 1.0 was released in August 2000; some pages say 2004.", "https://example.org/a")
    learn(j, "SQLite was first released in August 2000.", src)
    learn(j, "SQLite was first released in August 2004.", src)
    a, b = j.knowledge_of_kind(("conclusion",))
    assert a["status"] == b["status"] == "DISPUTED"
    return j, src, a["id"], b["id"]


def settle_objectives(j):
    derive_objectives(j, SelfModel(j))
    return [o for o in j.objectives(limit=200) if str(o["key"] or "").startswith("contradiction:")]


def own_task(j, o):
    t = j.start_task_sync("settle it", kind="autonomous")
    j.record_sync("cycle.completed", {"started": 0, "outcome": "RAN", "objective_id": o["id"], "task_id": t})
    return t


def filler(j, n):
    with j._txn() as cur:
        for i in range(n):
            j._insert_event(cur, time.time(), None, "test.filler", {"i": i})


# ——— derivation reads the DISPUTED rows ———


def test_an_old_dispute_still_gets_its_objective(tmp_path):
    j, _, a, b = disputed_pair(tmp_path)
    filler(j, 2100)  # the contradiction is older than the last 2000 events the derivation used to read
    found = settle_objectives(j)
    assert [o["key"] for o in found] == [f"contradiction:{a}:{b}"]
    o = found[0]
    assert o["check_spec"]["kind"] == "knowledge_stored" and o["check_spec"]["disputed"] == [a, b]
    assert o["evidence"]["knowledge_ids"] == [a, b] and o["goal"].startswith("My knowledge contradicts itself: ")
    assert settle_objectives(j) == found  # idempotent


def test_a_settled_pair_gets_no_objective(tmp_path):
    j, _, a, b = disputed_pair(tmp_path)
    fresh = web(j, "The first SQLite release, version 1.0, came out in August 2000.", "https://example.org/b")
    assert "SETTLED" in learn(j, "SQLite was first released in August 2000.", fresh)
    assert j.knowledge(a)["status"] == "ACTIVE" and j.knowledge(b)["status"] == "SUPERSEDED"
    assert settle_objectives(j) == []


def test_a_disputed_row_whose_other_side_is_gone_gets_an_objective_of_its_own(tmp_path):
    j, _, a, b = disputed_pair(tmp_path)
    j.forget_knowledge_sync([b], reason="test")
    found = settle_objectives(j)
    assert [o["key"] for o in found] == [f"contradiction:{a}"]
    assert found[0]["check_spec"]["disputed"] == [a]
    o = found[0]
    assert judge(j, o, None)[0] == "RETRY"
    j.verify_knowledge_sync(a, "confirmed independently", [1], resolve=True)
    verdict, ev = judge(j, o, None)
    assert verdict == "DONE" and ev["still_disputed"] == [] and ev["settled_by"]


# ——— the objective closes when its rows are no longer DISPUTED ———


def test_a_reinforcement_does_not_close_it_a_settlement_does(tmp_path):
    j, src, a, b = disputed_pair(tmp_path)
    o = settle_objectives(j)[0]
    t = own_task(j, o)
    # the same source again: a reinforcement of row a, both rows still DISPUTED
    out = learn(j, "SQLite was first released in August 2000.", src, task_id=t)
    assert "reinforced" in out and "SETTLED" not in out
    verdict, ev = judge(j, o, None)
    assert verdict == "RETRY" and sorted(ev["still_disputed"]) == [a, b]
    # forced through, the contract re-reads the rows and withdraws it
    assert contracts.assess(j, o, None, "DONE", {**ev, "matching": [a]}, path="existing")[0] == "RETRY"
    # independent evidence settles it: DONE, and the contract traces the settlement to the objective's own task
    fresh = web(j, "The first SQLite release, version 1.0, came out in August 2000.", "https://example.org/b", task_id=t)
    assert "SETTLED" in learn(j, "SQLite was first released in August 2000.", fresh, task_id=t)
    verdict, ev = judge(j, o, None)
    assert verdict == "DONE" and ev["still_disputed"] == [] and ev["states"] == {a: "ACTIVE", b: "SUPERSEDED"} and ev["settled_by"]
    verdict, c = contracts.assess(j, o, None, verdict, ev, path="existing")
    assert verdict == "DONE" and c["attribution"] == "own"
    assert any(e["type"] == "event" and e["id"] in ev["settled_by"] and e["task_id"] == t for e in c["evidence"])


def test_an_objective_an_older_version_opened_is_judged_by_its_rows(tmp_path):
    j, src, a, b = disputed_pair(tmp_path)
    # as the old derivation wrote it: no `disputed` in the check, the rows in the evidence
    o = j.add_objective_sync("My knowledge contradicts itself: ...", source="selfmodel", key=f"contradiction:{a}:{b}",
                             check={"kind": "knowledge_stored", "topic": "sqlite first released"}, evidence={"knowledge_ids": [a, b]})
    learn(j, "SQLite was first released in August 2000.", src)  # reinforced, still disputed
    assert judge(j, o, None)[0] == "RETRY"


# ——— only a believed row is evidence ———


def test_a_disputed_or_superseded_row_does_not_meet_a_knowledge_stored_check(tmp_path):
    j = Journal(tmp_path / "j.db")
    src = web(j, "SQLite 1.0 was released in August 2000; some pages say 2004.", "https://example.org/a")
    o = j.add_objective_sync("learn when sqlite was released", check={"kind": "knowledge_stored", "topic": "sqlite released"}, key="k")
    learn(j, "SQLite was first released in August 2000.", src)
    assert judge(j, o, None)[0] == "DONE"
    learn(j, "SQLite was first released in August 2004.", src)  # contradicts it: both rows DISPUTED
    verdict, ev = judge(j, o, None)
    assert verdict == "RETRY" and ev["matching"] == []
    a, b = [k["id"] for k in j.knowledge_of_kind(("conclusion",))]
    j.supersede_knowledge_sync([a], b, "test")  # b ACTIVE, a SUPERSEDED: only b counts
    verdict, ev = judge(j, o, None)
    assert verdict == "DONE" and ev["matching"] == [b]


def test_a_contract_does_not_rest_on_a_superseded_or_disputed_row(tmp_path):
    j = Journal(tmp_path / "j.db")
    o = j.add_objective_sync("learn about sqlite", check={"kind": "knowledge_stored", "topic": "sqlite"})
    t = own_task(j, o)
    old = web(j, "SQLite was first released in 2004.", "https://example.org/old", task_id=t)
    new = web(j, "SQLite was first released in 2000.", "https://example.org/new")
    j.supersede_knowledge_sync([old], new, "corrected")
    verdict, c = contracts.assess(j, o, None, "DONE", {"matching": [old]}, path="existing")
    assert verdict == "RETRY" and "could not be traced" in c["reason"]
    x = web(j, "SQLite stores data in a single file.", "https://example.org/x", task_id=t)
    y = web(j, "SQLite stores data in many files.", "https://example.org/y")
    j.dispute_knowledge_sync([x, y], "test")
    assert contracts.assess(j, o, None, "DONE", {"matching": [x]}, path="existing")[0] == "RETRY"
    # a stronger row asked for by knowledge_confidence: a DISPUTED one is neither judged nor contracted as one
    k = j.add_objective_sync("corroborate", check={"kind": "knowledge_confidence", "knowledge_id": y, "min": 0.3})
    t2 = own_task(j, k)
    z = web(j, "SQLite stores data in many files, says another page.", "https://example.org/z", task_id=t2)
    j.dispute_knowledge_sync([z, x], "test")
    verdict, ev = judge(j, k, None)
    assert verdict == "RETRY" and z not in ev["stronger"]
    assert contracts.assess(j, k, None, "DONE", {"stronger": [z]}, path="existing")[0] == "RETRY"
    # the ACTIVE row of the objective's own task still counts
    ok = web(j, "SQLite is a C library.", "https://example.org/ok", task_id=t)
    verdict, c = contracts.assess(j, o, None, "DONE", {"matching": [ok]}, path="existing")
    assert verdict == "DONE" and c["attribution"] == "own"


# ——— followup: what was learned is what is still believed ———


def test_a_retry_is_briefed_with_the_current_version_not_the_superseded_one(tmp_path):
    j = Journal(tmp_path / "j.db")
    old = web(j, "Take screenshots with the scrot command.", "https://example.org/old")
    new = web(j, "Take screenshots on Windows with PIL ImageGrab.", "https://example.org/new")
    gone = web(j, "Take screenshots with mss.", "https://example.org/mss")
    other = web(j, "Take screenshots with pyautogui only.", "https://example.org/pyautogui")
    j.supersede_knowledge_sync([old], new, "corrected")
    j.dispute_knowledge_sync([gone, other], "test")
    learn_o = j.add_objective_sync("learn screenshots", source="followup", check={"kind": "knowledge_stored", "topic": "screenshots"},
                                   evidence={"judged": {"matching": [old, gone]}})
    retry = j.add_objective_sync("take a screenshot", source="followup", check={"kind": "tool_verified", "tool": "desktop"},
                                 evidence={"learn_first": learn_o["id"]})
    brief = followup.learned_brief(j, retry)
    assert "PIL ImageGrab" in brief and f"#{new} " in brief
    assert "scrot" not in brief and "mss" not in brief


def test_a_blocked_objective_whose_learning_was_superseded_learns_first(tmp_path):
    j = Journal(tmp_path / "j.db")
    o = j.add_objective_sync("make desktop screenshots work", source="selfmodel", check={"kind": "tool_verified", "tool": "desktop"}, key="d")
    t = j.start_task_sync("attempt", kind="autonomous")
    stale = web(j, "Take screenshots with the scrot command.", "https://example.org/old", task_id=t)
    j.supersede_knowledge_sync([stale], web(j, "Take screenshots on Windows with PIL ImageGrab.", "https://example.org/new"), "corrected")
    j.update_objective_sync(o["id"], status="BLOCKED", last_task_id=t, progress={"attempts_log": [{"task_id": t, "lesson": "failed"}]})
    blocked = j.objective(o["id"])
    kinds = sorted(x["check_spec"]["kind"] for x in followup.derive(j, blocked))
    assert kinds == ["knowledge_stored", "tool_verified"]
