"""Phase 5: a conclusion learned twice is reinforced, not stored twice; one that
disagrees with what is stored is flagged and settled by research (live
2026-10-03: "SQLite was first released in 2000" was stored four times)."""

import asyncio

from syrax import consolidate
from syrax.autonomy import derive_objectives, judge
from syrax.journal import Journal
from syrax.research import KnowTool, LearnTool
from syrax.selfmodel import SelfModel


def setup(tmp_path):
    j = Journal(tmp_path / "j.db")
    web = j.add_knowledge_sync("SQLite 1.0 was released in August 2000 by D. Richard Hipp.", "web", source_url="https://sqlite.org/chronology.html", tags=["sqlite"])
    return j, LearnTool(journal=j), web["id"]


def learn(tool, claim, src):
    return asyncio.run(tool.execute(claim=claim, sources=[src]))


def test_figures_and_similarity():
    assert consolidate.figures("SQLite was first released in August 2000 (version 1.0).") == {"2000", "1.0"}
    assert consolidate.similarity("SQLite was first released in 2000.", "SQLite was first released in August 2000.") >= consolidate.SIMILAR
    assert consolidate.similarity("SQLite was first released in 2000.", "Python was created by Guido van Rossum.") < consolidate.SIMILAR


def test_the_same_conclusion_is_reinforced_not_stored_twice(tmp_path):
    j, tool, src = setup(tmp_path)
    first = learn(tool, "SQLite was first released in August 2000.", src)
    assert first.output.startswith("Learned id=")
    again = learn(tool, "SQLite was first released in 2000.", src)
    assert "Already known as id=" in again.output and "reinforced" in again.output
    assert len([k for k in j.knowledge_recent(limit=50) if k["kind"] == "conclusion"]) == 1
    o = j.add_objective_sync("learn when sqlite was released", check={"kind": "knowledge_stored", "topic": "sqlite released"}, key="k")
    learn(tool, "SQLite was first released in 2000.", src)  # after the objective: reinforcement is evidence too
    assert judge(j, o, None)[0] == "DONE"


def test_a_disagreeing_conclusion_is_flagged_shown_and_turned_into_an_objective(tmp_path):
    j, tool, src = setup(tmp_path)
    learn(tool, "SQLite was first released in August 2000.", src)
    out = learn(tool, "SQLite was first released in August 2004.", src).output
    assert "CONTRADICTS" in out
    ev = [e for e in j.recent_events(100) if e["type"] == "knowledge.contradiction"][-1]["payload"]
    shown = asyncio.run(KnowTool(journal=j).execute(query="sqlite first released")).output
    assert "DISPUTED" in shown
    derive_objectives(j, SelfModel(j))
    derive_objectives(j, SelfModel(j))  # idempotent
    found = [x for x in j.objectives(limit=50) if (x["key"] or "").startswith("contradiction:")]
    assert len(found) == 1
    o = found[0]
    assert sorted(o["evidence"]["knowledge_ids"]) == sorted([ev["knowledge_id"], *ev["conflicts_with"]])
    assert o["check_spec"]["kind"] == "knowledge_stored"


def test_unrelated_conclusions_with_different_numbers_do_not_conflict(tmp_path):
    j, tool, src = setup(tmp_path)
    learn(tool, "SQLite was first released in August 2000.", src)
    out = learn(tool, "Python 3.12 was released in October 2023.", src).output
    assert out.startswith("Learned id=") and "CONTRADICTS" not in out


def test_a_figure_at_the_end_of_a_sentence_counts():
    assert consolidate.figures("SQLite was first released in August 2000.") == {"2000"}
