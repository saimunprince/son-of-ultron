"""A web excerpt `research` already stored is reinforced, not stored again.

Live 2026-10-26: 169 of 680 knowledge rows came from quality runs, and the same
page excerpt was stored again and again (one SQLite-history excerpt 24 times,
an ethanol excerpt 11 times). Only `learn` conclusions were consolidated.
A web row whose (source_url, excerpt) equals a stored web row is now not
inserted; the stored row is reinforced (``knowledge.reinforced``, as
consolidate does for conclusions) and its id goes back to the model.
No network: the search engine and the page fetcher are fakes.
"""

import asyncio

from syrax import research
from syrax.journal import Journal
from syrax.research import Researcher, Source, render_report

PAGE_A = (
    "SQLite write-ahead logging. With synchronous=FULL in WAL mode an additional sync of the WAL file "
    "happens after each transaction commit, which makes transactions durable across a power loss. "
    "Other unrelated text about pandas and dataframes follows here for a while. " * 3
)
PAGE_B = (
    "The synchronous pragma applies to WAL mode too. FULL syncs the WAL after every commit so a "
    "transaction is durable after power loss; NORMAL only syncs at checkpoints. " * 3
)
PAGE_B2 = (
    "Revised: the synchronous pragma in WAL mode with FULL syncs the WAL file on each commit, so a "
    "commit is durable even after a power loss or crash; NORMAL is faster. " * 3
)
Q = "what does sqlite synchronous FULL guarantee in WAL mode"
RESULTS = [("http://a", "Page A", "sqlite wal"), ("http://b", "Page B", "pragma")]


def fake_engine(results):
    def engine(query, max_results):
        return [Source(url=u, title=t, snippet=sn, engine="fake") for u, t, sn in results][:max_results]
    return engine


def researcher(j, monkeypatch, results, pages):
    monkeypatch.setattr(research, "ENGINES", [fake_engine(results)])
    t = j.start_task_sync("research test")

    async def fetch(url):
        return pages.get(url)

    return Researcher(j, task_id_provider=lambda: t, fetcher=fetch), t


def test_the_same_excerpt_twice_is_reinforced_not_stored_again(tmp_path, monkeypatch):
    j = Journal(tmp_path / "j.db")
    pages = {"http://a": PAGE_A, "http://b": PAGE_B}
    r1, _ = researcher(j, monkeypatch, RESULTS, pages)
    first = asyncio.run(r1.research(Q, 2))
    assert first["stored"] == 2 and first["reinforced"] == 0 and j.count("knowledge") == 2
    r2, t2 = researcher(j, monkeypatch, RESULTS, pages)
    second = asyncio.run(r2.research(Q, 2))
    assert j.count("knowledge") == 2  # nothing new
    assert second["stored"] == 0 and second["reinforced"] == 2
    # the model gets the same sources with the stored rows' ids
    assert [(s["url"], s["knowledge_id"]) for s in second["sources"]] == [(s["url"], s["knowledge_id"]) for s in first["sources"]]
    assert [s["excerpts"] for s in second["sources"]] == [s["excerpts"] for s in first["sources"]]
    events = j.events(t2)
    assert [e["type"] for e in events] == ["task.started", "research.started", "knowledge.reinforced", "knowledge.reinforced", "research.completed"]
    ids = {s["knowledge_id"] for s in first["sources"]}
    reinforced = [e["payload"] for e in events if e["type"] == "knowledge.reinforced"]
    assert {p["knowledge_id"] for p in reinforced} == ids
    for p in reinforced:  # the autonomy knowledge_stored check reads claim and tags from this event
        row = j.knowledge(p["knowledge_id"])
        assert p["kind"] == "web" and p["claim"] == row["claim"][:300] and p["tags"] == row["tags"] and p["question"] == Q
    done = [e["payload"] for e in events if e["type"] == "research.completed"][0]
    assert done["stored"] == 0 and done["reinforced"] == 2
    text = render_report(second)
    assert "Stored 0 knowledge entries" in text and "2 already known" in text and "reinforced" in text
    for kid in ids:
        assert f"knowledge_id={kid}" in text


def test_a_changed_excerpt_or_another_url_is_stored(tmp_path, monkeypatch):
    j = Journal(tmp_path / "j.db")
    r1, _ = researcher(j, monkeypatch, RESULTS, {"http://a": PAGE_A, "http://b": PAGE_B})
    first = asyncio.run(r1.research(Q, 2))
    by_url = {s["url"]: s["knowledge_id"] for s in first["sources"]}
    # page B changed: a new excerpt from the same URL is new evidence; page A is the same
    r2, _ = researcher(j, monkeypatch, RESULTS, {"http://a": PAGE_A, "http://b": PAGE_B2})
    second = asyncio.run(r2.research(Q, 2))
    assert second["stored"] == 1 and second["reinforced"] == 1 and j.count("knowledge") == 3
    got = {s["url"]: s["knowledge_id"] for s in second["sources"]}
    assert got["http://a"] == by_url["http://a"] and got["http://b"] not in by_url.values()
    # the same text on another URL is another source, so it is stored
    r3, _ = researcher(j, monkeypatch, [("http://mirror", "Mirror", "sqlite wal")], {"http://mirror": PAGE_A})
    third = asyncio.run(r3.research(Q, 1))
    assert third["stored"] == 1 and third["reinforced"] == 0 and j.count("knowledge") == 4


def test_only_web_rows_with_the_same_url_and_excerpt_match(tmp_path):
    j = Journal(tmp_path / "j.db")
    assert j.web_knowledge_like("http://a", "x") is None
    j.add_knowledge_sync("a local note", "local", source_url="http://a", excerpt="same text")
    assert j.web_knowledge_like("http://a", "same text") is None  # another kind is not a web duplicate
    old = j.add_knowledge_sync("old copy", "web", source_url="http://a", excerpt="same text")
    j.add_knowledge_sync("newer copy", "web", source_url="http://a", excerpt="same text")
    assert j.web_knowledge_like("http://a", "same text")["id"] == old["id"]  # copies stored before: the oldest
    assert j.web_knowledge_like("http://a", "other text") is None
    assert j.web_knowledge_like("http://b", "same text") is None
    assert j.web_knowledge_like("", "same text") is None and j.web_knowledge_like("http://a", "") is None
    assert j.web_knowledge_like("http://a", None) is None
    # compared as stored: the excerpt column keeps the first 2000 characters
    long = "w" * 2500
    kept = j.add_knowledge_sync("long excerpt", "web", source_url="http://long", excerpt=long)
    assert j.web_knowledge_like("http://long", long)["id"] == kept["id"]
    # reading is not using: uses and last_used are untouched
    row = j.knowledge(old["id"])
    assert row["uses"] == 0 and row["last_used"] is None
