"""Watched topics: the list lives in the journal, each topic is looked up at
most once a day, only stories never reported before are reported, and the
briefing lists them. The news search is faked; no network."""

import asyncio
import time

import pytest

from syrax import briefing, permissions, topics
from syrax import autonomy as auto
from syrax.journal import Journal
from syrax.test_autonomy import make

NOW = 1_800_000_000.0


def story(n):
    return {"title": f"Story {n}", "url": f"https://news.example/{n}", "source": "Example", "date": "2026-10-12"}


def test_the_list_keeps_the_humans_spelling_and_removes(tmp_path):
    j = Journal(tmp_path / "j.db")
    assert topics.watch(j, "  AI   chips ") == "AI chips"
    topics.watch(j, "Bangladesh cricket")
    topics.watch(j, "ai chips")  # already watched
    assert topics.watched(j) == ["AI chips", "Bangladesh cricket"]
    assert topics.unwatch(j, "ai CHIPS") and topics.watched(j) == ["Bangladesh cricket"]
    assert not topics.unwatch(j, "nothing")
    with pytest.raises(ValueError):
        topics.watch(j, "x")


def test_only_new_stories_once_a_day(tmp_path):
    j = Journal(tmp_path / "j.db")
    topics.watch(j, "AI chips")
    batches = [[story(1), story(2)], [story(2), story(3)]]
    found = asyncio.run(topics.check(j, fetch=lambda t: batches[0], now=NOW))
    assert [i["url"] for i in found[0]["items"]] == ["https://news.example/1", "https://news.example/2"]
    assert asyncio.run(topics.check(j, fetch=lambda t: batches[1], now=NOW + 3600)) == []  # checked today already
    later = asyncio.run(topics.check(j, fetch=lambda t: batches[1], now=NOW + topics.EVERY_S + 1))
    assert [i["url"] for i in later[0]["items"]] == ["https://news.example/3"]  # story 2 is never reported twice


def test_offline_is_tried_again_and_the_briefing_lists_the_news(tmp_path):
    j = Journal(tmp_path / "j.db")
    topics.watch(j, "AI chips")

    def offline(t):
        raise OSError("no network")

    assert asyncio.run(topics.check(j, fetch=offline, now=NOW)) == []
    assert topics.due(j, NOW + 60) == ["AI chips"]  # not marked checked
    asyncio.run(topics.check(j, fetch=lambda t: [story(7)], now=time.time()))
    text = briefing.compose(j, time.time() - 3600)
    assert "- news on watched topics:" in text and "AI chips: Story 7 (Example)" in text


def test_the_tool_and_its_level(tmp_path):
    j = Journal(tmp_path / "j.db")
    tool = topics.WatchTopicTool(journal_provider=lambda: j)
    assert asyncio.run(tool.execute(action="add", topic="AI chips")).output.startswith("Watching 'AI chips'")
    assert asyncio.run(tool.execute(action="list")).output == "Watching: AI chips"
    assert asyncio.run(tool.execute(action="remove", topic="AI chips")).output == "No longer watching 'AI chips'."
    assert asyncio.run(tool.execute(action="remove", topic="AI chips")).error
    assert permissions.level_of_tool("watch_topic") == permissions.WRITE


def test_the_idle_cycle_checks_due_topics_when_the_service_asks(tmp_path, monkeypatch):
    j, core, a = make(tmp_path, tools=["terminate"])
    a.set_enabled(True)
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    for k in ("SYRAX_PUBLISH_RISE", "SYRAX_CODEBENCH"):
        monkeypatch.delenv(k, raising=False)
    topics.watch(j, "AI chips")
    calls = []

    async def fake_check(journal, fetch=None, now=None):
        calls.append(journal)
        return [{"topic": "AI chips", "items": [story(1)]}]

    monkeypatch.setattr(topics, "check", fake_check)
    monkeypatch.delenv("SYRAX_FEATURES", raising=False)
    assert asyncio.run(a.run_once()).outcome == "IDLE" and calls == []
    monkeypatch.setenv("SYRAX_FEATURES", "1")
    rep = asyncio.run(a.run_once())
    assert rep.outcome == "RAN" and rep.reason == "watched topics: 1 new stories" and calls == [j]
