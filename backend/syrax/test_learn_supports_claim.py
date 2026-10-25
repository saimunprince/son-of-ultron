"""Memory truth (2026-10-25 audit): `learn` used to check only that the cited knowledge_ids exist, so any row could
be cited for any claim. A cited row must support the claim: share three content words (lower-cased, no stopwords,
4+ letters) or a number/year with it. A row that shares nothing is refused and nothing is stored; a row that shares
a word or two is weak support (test_consolidate cites an SQLite row for a Python release): stored at half the cap
and labelled. The existing caps stay."""

import asyncio

from syrax.journal import Journal
from syrax.research import SUPPORT_WORDS, LearnTool, support

CLAIM = "SQLite was first released in August 2000."


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def setup(tmp_path):
    j = Journal(tmp_path / "j.db")
    sqlite = j.add_knowledge_sync("SQLite 1.0 was released in August 2000 by D. Richard Hipp.", "web",
                                  source_url="https://sqlite.org/chronology.html", agreeing_sources=2)
    rice = j.add_knowledge_sync("Rinse the rice, add water, simmer and rest.", "web", source_url="https://cook.example/rice")
    return j, LearnTool(journal=j), sqlite, rice


def conclusions(j):
    return [k for k in j.knowledge_recent(limit=50) if k["kind"] == "conclusion"]


def test_a_supporting_row_stores_the_conclusion(tmp_path):
    j, tool, sqlite, rice = setup(tmp_path)
    assert support(CLAIM, sqlite) == SUPPORT_WORDS  # sqlite, released, august (and the year)
    out = run(tool.execute(claim=CLAIM, sources=[sqlite["id"]]))
    assert not out.error and out.output.startswith("Learned id=") and "Weak support" not in out.output
    row = conclusions(j)[0]
    assert row["confidence"] == 0.6 and row["sources"] == [sqlite["id"]] and "weak" not in row["basis"]


def test_an_unrelated_row_is_refused_and_nothing_is_stored(tmp_path):
    j, tool, sqlite, rice = setup(tmp_path)
    assert support(CLAIM, rice) == 0
    before = j.count("knowledge")
    out = run(tool.execute(claim=CLAIM, sources=[rice["id"]], confidence=0.9))
    assert out.error == f"learn refused: knowledge_id {rice['id']} does not support the claim: cite the rows whose text does"
    assert j.count("knowledge") == before and conclusions(j) == []
    assert not any(e["type"] in ("knowledge.stored", "knowledge.reinforced") and e["payload"].get("kind") == "conclusion"
                   for e in j.recent_events(100))
    # a supporting row beside an unrelated one: the unrelated one is named, still nothing is stored
    out = run(tool.execute(claim=CLAIM, sources=[sqlite["id"], rice["id"]]))
    assert out.error and f"knowledge_id {rice['id']} does not support the claim" in out.error
    assert j.count("knowledge") == before


def test_a_shared_year_counts_as_support(tmp_path):
    j, tool, sqlite, rice = setup(tmp_path)
    claim = "The first public release of the engine dates from 2000."  # no content word in common, the year is
    assert support(claim, sqlite) == SUPPORT_WORDS and support(claim, rice) == 0
    out = run(tool.execute(claim=claim, sources=[sqlite["id"]]))
    assert not out.error and out.output.startswith("Learned id=") and "Weak support" not in out.output
    assert conclusions(j)[0]["confidence"] == 0.6
    # a single digit is not a number worth sharing
    assert support("Step 1 of the recipe.", {"claim": "Chapter 1 of the SQLite book.", "excerpt": ""}) == 0


def test_a_row_sharing_a_word_or_two_is_weak_support_at_half_the_cap(tmp_path):
    j, tool, sqlite, rice = setup(tmp_path)
    claim = "Python 3.12 was released in October 2023."  # shares only "released"
    assert 0 < support(claim, sqlite) < SUPPORT_WORDS
    out = run(tool.execute(claim=claim, sources=[sqlite["id"]], confidence=0.99))
    assert not out.error and out.output.startswith("Learned id=") and f"Weak support: knowledge_id {sqlite['id']}" in out.output
    row = conclusions(j)[0]
    assert row["confidence"] == 0.3 and "weak support" in row["basis"] and "cap halved" in row["basis"]
