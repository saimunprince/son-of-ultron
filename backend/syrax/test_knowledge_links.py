"""EVOLUTION_PLAN wave 4 (directions 56 associative retrieval, 61 knowledge graph, 69 cross-domain integration):
stored facts were found only by shared words. A claim of a plain form ("X uses Y", "X runs on Y", "X was released in
Y") now leaves subject-relation-object links, and `know` follows a shared name one hop to related facts."""

import asyncio

from syrax.journal import Journal, links_of
from syrax.research import KnowTool


def test_plain_claims_give_links_and_vague_ones_do_not():
    assert links_of("SYRAX uses SQLite for its journal.") == [("syrax", "uses", "sqlite")]
    assert links_of("SYRAX runs on a laptop with 14 GB of RAM") == [("syrax", "runs on", "laptop with 14 gb of ram")]
    assert ("python 3.12", "was released in", "october 2023") in links_of("Python 3.12 was released in October 2023.")
    assert links_of("it is fast and it works well") == []
    assert links_of("This is a list of capitals. What is the capital? France This is a city.") == []


def test_know_follows_a_shared_name_to_a_fact_the_words_missed(tmp_path):
    j = Journal(tmp_path / "j.db")
    a = j.add_knowledge_sync("SYRAX uses SQLite as its journal store.", "local", source_url="file:///repo/journal.py")
    b = j.add_knowledge_sync("SQLite runs on every major operating system.", "web", source_url="https://sqlite.org/about.html")
    out = asyncio.run(KnowTool(journal=j).execute(query="SYRAX journal store")).output
    assert f"id={a['id']}" in out and "RELATED" in out and f"id={b['id']}" in out


def test_an_existing_journal_is_backfilled_once(tmp_path):
    j = Journal(tmp_path / "j.db")
    k = j.add_knowledge_sync("Groq runs on LPU hardware.", "web", source_url="https://groq.com")
    j._db.execute("DELETE FROM knowledge_links")
    j.close()
    j2 = Journal(tmp_path / "j.db")
    n = j2._db.execute("SELECT COUNT(*) FROM knowledge_links WHERE knowledge_id=?", (k["id"],)).fetchone()[0]
    assert n == 1
