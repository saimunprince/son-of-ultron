"""2026-10-19 (research_cite) and 2026-10-17 (act_concise): the brain cited "knowledge_id=536", the way `research`
prints a source, and learn refused it with "cite at least one knowledge_id or URL", twice in a row each time; the
conclusion was never stored. A source written as research ("knowledge_id=536") or know ("id=536") prints it is read."""

import asyncio

from syrax.journal import Journal
from syrax.research import LearnTool


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_sources_written_as_research_and_know_print_them_are_read(tmp_path):
    j = Journal(tmp_path / "j.db")
    a = j.add_knowledge_sync(claim="SQLite 1.0 was released in August 2000.", kind="web",
                             source_url="https://www.sqlite.org/chronology.html", confidence=0.8)
    b = j.add_knowledge_sync(claim="The first public SQLite release dates from 2000-08-17.", kind="web",
                             source_url="https://en.wikipedia.org/wiki/SQLite", confidence=0.7)
    out = run(LearnTool(journal=j).execute(claim="SQLite was first released in August 2000.",
                                           sources=[f"knowledge_id={a['id']}", f"id={b['id']}"]))
    assert not out.error, out.error
    assert out.output.startswith("Learned id=")
    learned = j.knowledge(int(out.output.split("id=")[1].split()[0]))
    assert sorted(learned["sources"]) == sorted([a["id"], b["id"]])


def test_a_source_that_names_nothing_is_still_refused(tmp_path):
    j = Journal(tmp_path / "j.db")
    out = run(LearnTool(journal=j).execute(claim="SQLite was first released in August 2000.", sources=["the docs", "knowledge_id="]))
    assert out.error == "learn refused: cite at least one knowledge_id or URL"
