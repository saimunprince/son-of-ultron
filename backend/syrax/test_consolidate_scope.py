"""A new conclusion is compared with every stored conclusion, and a duplicate stays a duplicate
when another row conflicts (audit 2026-10-27: "SQLite was first released in 2000" was stored again
412 rows after the first copy because only the last 300 rows of any kind were compared, and three
identical ethanol rows were stored because a conflicting row skipped the duplicate check)."""

import asyncio

from syrax import consolidate
from syrax.journal import Journal
from syrax.research import LearnTool


def journal_with_source(tmp_path):
    j = Journal(tmp_path / "j.db")
    web = j.add_knowledge_sync("SQLite 1.0 was released in August 2000; pure ethanol boils at 78.37 degrees Celsius.",
                               "web", source_url="https://example.org/facts", tags=["facts"])
    return j, web["id"]


def bury(j, n=400):
    for i in range(n):
        j.add_knowledge_sync(f"Unrelated web page number {i} about topic t{i} and subject s{i}.", "web",
                             source_url=f"https://example.org/page/{i}", excerpt=f"excerpt {i}")


def conclusions(j):
    return j.knowledge_of_kind(("conclusion",))


def learn(j, claim, src):
    return asyncio.run(LearnTool(journal=j).execute(claim=claim, sources=[src])).output


def test_an_old_conclusion_behind_400_web_rows_is_still_a_duplicate(tmp_path):
    j, src = journal_with_source(tmp_path)
    old = j.add_knowledge_sync("SQLite was first released in 2000.", "conclusion", sources=[src])
    bury(j)
    duplicate, conflicts = consolidate.compare("SQLite was first released in 2000.", j)
    assert conflicts == [] and duplicate is not None and duplicate["id"] == old["id"]
    out = learn(j, "SQLite was first released in 2000.", src)
    assert f"Already known as id={old['id']}" in out and "reinforced" in out
    assert len(conclusions(j)) == 1


def test_an_old_conclusion_behind_400_web_rows_is_still_contradicted(tmp_path):
    j, src = journal_with_source(tmp_path)
    old = j.add_knowledge_sync("SQLite was first released in 2000.", "conclusion", sources=[src])
    bury(j)
    duplicate, conflicts = consolidate.compare("SQLite was first released in 2004.", j)
    assert duplicate is None and [k["id"] for k in conflicts] == [old["id"]]


def test_a_duplicate_that_also_conflicts_with_a_third_row_is_still_a_duplicate(tmp_path):
    j, src = journal_with_source(tmp_path)
    same = j.add_knowledge_sync("Pure ethanol boils at 78.37 degrees Celsius.", "conclusion", sources=[src])
    other = j.add_knowledge_sync("Pure ethanol boils at 82 degrees Celsius.", "conclusion", sources=[src])
    claim = "Pure ethanol boils at 78.37 degrees Celsius."
    duplicate, conflicts = consolidate.compare(claim, j)
    assert duplicate is not None and duplicate["id"] == same["id"]
    assert [k["id"] for k in conflicts] == [other["id"]]
    for _ in range(3):  # live: rows 575, 648 and 676 were the same claim stored three times
        out = learn(j, claim, src)
        assert f"Already known as id={same['id']}" in out and "reinforced" in out
        assert "CONTRADICTS" in out and f"id={other['id']}" in out
    assert [k["id"] for k in conclusions(j)] == [same["id"], other["id"]]
    ev = [e["payload"] for e in j.recent_events(200) if e["type"] == "knowledge.contradiction"]
    assert ev and ev[-1]["knowledge_id"] == same["id"] and ev[-1]["conflicts_with"] == [other["id"]]
