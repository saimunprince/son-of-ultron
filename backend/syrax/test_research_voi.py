"""EVOLUTION_PLAN direction 144 (value-of-information analysis): `research` searched the web every time, even when
fresh, sourced knowledge already answered the question (the prompt only asked to check `know` first). When at least
two ACTIVE, fresh, confident rows cover the question's words, they are returned and no search is made; force=true
searches anyway."""

import asyncio

from syrax.journal import Journal
from syrax.research import ResearchTool, already_known


class FakeResearcher:
    def __init__(self, journal):
        self.journal, self.asked = journal, []

    async def research(self, question, max_sources=4):
        self.asked.append(question)
        return {"question": question, "sources": [], "knowledge_ids": [], "excerpts": [], "search_failures": [], "reinforced": []}


def setup(tmp_path):
    j = Journal(tmp_path / "j.db")
    for i, url in enumerate(("https://a.org", "https://b.org")):
        j.add_knowledge_sync(f"SQLite WAL mode lets readers and a writer work concurrently ({i})", "web", source_url=url,
                             question="how does sqlite wal mode handle concurrent readers", agreeing_sources=2)
    return j


def test_fresh_sourced_knowledge_answers_without_a_web_search(tmp_path):
    j = setup(tmp_path)
    r = FakeResearcher(j)
    out = asyncio.run(ResearchTool(researcher=r).execute(question="How does SQLite WAL mode handle concurrent readers?")).output
    assert out.startswith("ALREADY KNOWN (2") and r.asked == []
    asyncio.run(ResearchTool(researcher=r).execute(question="How does SQLite WAL mode handle concurrent readers?", force=True))
    assert len(r.asked) == 1


def test_an_unanswered_question_is_researched(tmp_path):
    j = setup(tmp_path)
    r = FakeResearcher(j)
    asyncio.run(ResearchTool(researcher=r).execute(question="What is the default page size of PostgreSQL?"))
    assert r.asked and already_known(j, "What is the default page size of PostgreSQL?") == []
