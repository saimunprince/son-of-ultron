"""EVOLUTION_PLAN direction 241 (automated literature review): `research` searched the open web only. paper_search asks
arXiv's public API (no key), parses the Atom feed with the standard library, stores each paper as web knowledge with
its URL, and marks the output UNTRUSTED. These tests use a recorded feed; one live call checks the real API's shape."""

import asyncio

from syrax import paper_research as P
from syrax.journal import Journal
from syrax.redact import UNTRUSTED_WEB

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2005.11401v4</id>
    <published>2020-05-22T17:52:49Z</published>
    <title>Retrieval-Augmented Generation for
      Knowledge-Intensive NLP Tasks</title>
    <summary>  Large pre-trained language models have been shown to store factual knowledge.  </summary>
    <author><name>Patrick Lewis</name></author><author><name>Ethan Perez</name></author>
    <author><name>Aleksandra Piktus</name></author><author><name>Fabio Petroni</name></author>
  </entry>
</feed>"""


def test_the_feed_is_parsed():
    (p,) = P.parse(FEED)
    assert p["title"] == "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks"
    assert p["published"] == "2020-05-22" and p["url"] == "http://arxiv.org/abs/2005.11401v4"
    assert p["authors"][:2] == ["Patrick Lewis", "Ethan Perez"] and p["summary"].startswith("Large pre-trained")


def test_each_paper_becomes_sourced_knowledge_and_the_output_is_untrusted(tmp_path):
    j = Journal(tmp_path / "j.db")

    async def fake(query, limit):
        return P.parse(FEED)

    out = asyncio.run(P.PaperSearchTool(journal=j, searcher=fake).execute(query="retrieval augmented generation")).output
    assert out.startswith(UNTRUSTED_WEB) and "knowledge_id=1" in out and "et al." in out
    k = j.knowledge(1)
    assert k["source_url"] == "http://arxiv.org/abs/2005.11401v4" and "paper" in k["tags"] and k["kind"] == "web"
    assert [e for e in j.recent_events(20) if e["type"] == "paper.searched"][-1]["payload"]["results"] == 1


def test_errors_and_empty_queries_are_said():
    async def broken(query, limit):
        raise RuntimeError("HTTP 503")

    assert "failed" in asyncio.run(P.PaperSearchTool(searcher=broken).execute(query="x")).error
    assert asyncio.run(P.PaperSearchTool().execute(query="  ")).error
