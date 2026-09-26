"""Research + knowledge tests. No network: search engines and the page fetcher
are replaced with fakes; the journal, extraction, provenance and confidence
policy are real."""

import asyncio

import pytest

from syrax import research
from syrax.journal import Journal, JournalError, confidence_for
from syrax.research import (
    KnowTool,
    LearnTool,
    Researcher,
    ResearchTool,
    Source,
    agreement,
    extract_excerpts,
    keywords,
    render_report,
    search,
)

PAGE_A = (
    "SQLite write-ahead logging. With synchronous=FULL in WAL mode an additional sync of the WAL file "
    "happens after each transaction commit, which makes transactions durable across a power loss. "
    "Other unrelated text about pandas and dataframes follows here for a while. " * 3
)
PAGE_B = (
    "The synchronous pragma applies to WAL mode too. FULL syncs the WAL after every commit so a "
    "transaction is durable after power loss; NORMAL only syncs at checkpoints. " * 3
)
PAGE_C = "A page about cooking rice. Rinse the rice, add water, simmer, rest. " * 6


def fake_engine(results):
    def engine(query, max_results):
        return [Source(url=u, title=t, snippet=sn, engine="fake") for u, t, sn in results][:max_results]
    return engine


def fake_fetcher(pages):
    async def fetch(url):
        return pages.get(url)
    return fetch


def make(tmp_path, monkeypatch, results, pages):
    j = Journal(tmp_path / "j.db")
    monkeypatch.setattr(research, "ENGINES", [fake_engine(results)])
    t = j.start_task_sync("research test")  # events are task-bound, so the task must exist
    r = Researcher(j, task_id_provider=lambda: t, fetcher=fake_fetcher(pages))
    r.task_id = t
    return j, r


# ——— extraction + policy ———


def test_keywords_and_excerpts_follow_the_question():
    assert "sqlite" in keywords("What does SQLite synchronous=FULL guarantee?") and "what" not in keywords("what is")
    ex = extract_excerpts(PAGE_A, "sqlite synchronous FULL WAL durable power loss")
    assert ex and "synchronous=FULL" in ex[0] and len(ex) <= 2
    assert extract_excerpts(PAGE_C, "sqlite synchronous FULL WAL") == []
    assert extract_excerpts("", "x") == []


def test_agreement_counts_sources_sharing_terms():
    a = Source(url="a", terms={"sqlite", "wal", "sync", "durable"})
    b = Source(url="b", terms={"sqlite", "wal", "sync", "commit"})
    c = Source(url="c", terms={"rice", "water"})
    assert agreement([a, b, c]) == {"a": 2, "b": 2, "c": 1}


def test_confidence_policy_is_evidence_based(tmp_path):
    assert confidence_for("web", 1) == 0.4 and confidence_for("web", 2) == 0.6 and confidence_for("web", 5) == 0.75
    assert confidence_for("experiment") == 0.95 and confidence_for("human") == 1.0
    j = Journal(tmp_path / "j.db")
    k = j.add_knowledge_sync("x", "web", source_url="http://a", agreeing_sources=1, confidence=0.99)
    assert k["confidence"] == 0.4  # cannot exceed policy
    k = j.add_knowledge_sync("x", "web", source_url="http://a", agreeing_sources=3, confidence=0.5)
    assert k["confidence"] == 0.5  # may be lowered
    with pytest.raises(JournalError):
        j.add_knowledge_sync("orphan", "web")  # no source
    with pytest.raises(JournalError):
        j.add_knowledge_sync("", "human")
    with pytest.raises(JournalError):
        j.add_knowledge_sync("x", "gossip", source_url="http://a")
    h = j.add_knowledge_sync("Prince prefers Banglish.", "human", tags=["Prince", "style"])
    assert h["confidence"] == 1.0 and h["tags"] == ["prince", "style"]
    assert [e["type"] for e in j.recent_events()] == ["knowledge.stored"] * 3


def test_knowledge_search_ranks_and_counts_uses(tmp_path):
    j = Journal(tmp_path / "j.db")
    a = j.add_knowledge_sync("SQLite WAL mode syncs the log on commit", "web", source_url="http://a", tags=["sqlite", "wal"])
    b = j.add_knowledge_sync("Rice needs water", "web", source_url="http://b", tags=["rice"])
    hits = j.knowledge_search("sqlite wal commit")
    assert [k["id"] for k in hits] == [a["id"]]
    assert j.knowledge(a["id"])["uses"] == 1 and j.knowledge(b["id"])["uses"] == 0
    assert j.knowledge_search("") == [] and j.knowledge_search("zzz") == []
    assert [k["id"] for k in j.knowledge_recent(tag="rice")] == [b["id"]]


# ——— the engine ———


def test_research_stores_excerpts_with_provenance_and_agreement(tmp_path, monkeypatch):
    j, r = make(
        tmp_path, monkeypatch,
        [("http://a", "Page A", "sqlite wal"), ("http://b", "Page B", "pragma"), ("http://c", "Rice", "rice")],
        {"http://a": PAGE_A, "http://b": PAGE_B, "http://c": PAGE_C},
    )
    rep = asyncio.run(r.research("what does sqlite synchronous FULL guarantee in WAL mode", 3))
    assert rep["fetched"] == 3 and rep["stored"] == 2  # the rice page has nothing relevant
    by_url = {s["url"]: s for s in rep["sources"]}
    assert by_url["http://a"]["agreeing"] == 2 and by_url["http://b"]["agreeing"] == 2 and by_url["http://c"]["excerpts"] == []
    rows = j.knowledge_recent()
    assert len(rows) == 2 and all(k["kind"] == "web" and k["task_id"] == r.task_id for k in rows)
    a = [k for k in rows if k["source_url"] == "http://a"][0]
    assert a["confidence"] == 0.6 and "synchronous=FULL" in a["claim"] and "2 source(s)" in a["basis"]
    assert "sqlite" in a["tags"] and a["question"].startswith("what does sqlite")
    kinds = [e["type"] for e in j.events(r.task_id)]
    assert kinds == ["task.started", "research.started", "knowledge.stored", "knowledge.stored", "research.completed"]
    text = render_report(rep)
    assert "knowledge_id=" in text and "Stored 2 knowledge entries" in text and "not conclusions" in text


def test_research_with_no_results_is_unknown_not_fabricated(tmp_path, monkeypatch):
    j = Journal(tmp_path / "j.db")

    def broken(query, n):
        raise RuntimeError("engine down")

    monkeypatch.setattr(research, "ENGINES", [broken, fake_engine([])])
    r = Researcher(j, fetcher=fake_fetcher({}))
    rep = asyncio.run(r.research("anything", 2))
    assert rep["sources"] == [] and rep["stored"] == 0
    assert any("engine down" in f for f in rep["search_failures"]) and any("no results" in f for f in rep["search_failures"])
    assert "UNKNOWN" in render_report(rep) and j.count("knowledge") == 0


def test_research_uses_snippet_when_page_cannot_be_fetched(tmp_path, monkeypatch):
    j, r = make(tmp_path, monkeypatch, [("http://a", "A", "sqlite wal sync commit durable")], {})
    rep = asyncio.run(r.research("sqlite wal sync durable", 1))
    assert rep["fetched"] == 0 and rep["stored"] == 1
    k = j.knowledge_recent()[0]
    assert "NOT fetched" in k["basis"] and k["confidence"] == 0.4


def test_search_falls_through_engines(monkeypatch):
    calls = []

    def e1(q, n):
        calls.append("e1")
        return []

    def e2(q, n):
        calls.append("e2")
        return [Source(url="http://x", title="X")]

    monkeypatch.setattr(research, "ENGINES", [e1, e2])
    found, failures = asyncio.run(search("q", 3))
    assert [s.url for s in found] == ["http://x"] and calls == ["e1", "e2"] and failures == ["e1: no results"]


# ——— tools ———


def test_tools_refuse_without_store_and_learn_is_capped_by_evidence(tmp_path, monkeypatch):
    assert asyncio.run(ResearchTool().execute(question="x")).error
    assert asyncio.run(KnowTool().execute(query="x")).error
    assert asyncio.run(LearnTool().execute(claim="x", sources=[1])).error
    j, r = make(tmp_path, monkeypatch, [("http://a", "A", "sqlite wal durable commit sync")], {"http://a": PAGE_A})
    tool = ResearchTool(); tool.researcher = r
    out = asyncio.run(tool.execute(question="sqlite wal synchronous full durable"))
    assert not out.error and "knowledge_id=1" in out.output
    know = KnowTool(); know.journal = j
    assert "id=1" in asyncio.run(know.execute(query="sqlite wal")).output
    assert "Nothing stored" in asyncio.run(know.execute(query="bananas")).output
    learn = LearnTool(); learn.journal = j; learn.task_id_provider = lambda: r.task_id
    refused = asyncio.run(learn.execute(claim="FULL is durable", sources=[]))
    assert refused.error and "cite" in refused.error
    unknown = asyncio.run(learn.execute(claim="x", sources=[42]))
    assert unknown.error and "42" in unknown.error
    ok = asyncio.run(learn.execute(claim="synchronous=FULL makes WAL commits durable across power loss", sources=[1], confidence=0.99))
    assert not ok.error and "confidence 0.40" in ok.output  # capped by the single web source (0.4)
    row = j.knowledge_recent()[0]
    assert row["kind"] == "conclusion" and row["sources"] == [1] and row["confidence"] == 0.4 and row["task_id"] == r.task_id
    empty = asyncio.run(tool.execute(question="   "))
    assert empty.error


def test_research_tool_reports_engine_crash_as_error(tmp_path, monkeypatch):
    j = Journal(tmp_path / "j.db")

    class Boom:
        async def research(self, q, n):
            raise RuntimeError("kaboom")

    tool = ResearchTool(); tool.researcher = Boom()
    out = asyncio.run(tool.execute(question="q"))
    assert out.error and "kaboom" in out.error
