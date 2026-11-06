"""Round 12, 2026-11-06: (1) a made-up paper was answered, with no tool run, as "searches in academic repositories
such as Zenodo return no such work" plus a link; (2) "Glarnovia" was researched, nothing found, and the citation
nudge got Genoa's Wikipedia page cited. A claimed search must have run; "nothing found" needs no URL."""

from syrax.test_bridge import call, reply, script, server  # noqa: F401
from syrax.test_change_proof import run


def test_a_search_claimed_with_no_tool_is_sent_back(script):
    script.queue = [
        reply("There is no record of it; searches in academic repositories such as Zenodo return no such work."),
        reply("I do not know any 2027 paper by that name, and I did not search for it."),
    ]
    task, _ = run("Summarize the 2027 paper 'Quantum Banana Networks' by Dr. Zorbulon Kett.")
    assert task["result"].startswith("I do not know any 2027 paper") and not script.queue


def test_nothing_found_after_research_is_not_asked_for_a_url(script):
    script.queue = [
        call("research", {"question": "Glarnovia population"}),
        reply("I found no record of a city called Glarnovia."),
    ]
    task, _ = run("What is the population of the city of Glarnovia?")
    assert task["result"] == "I found no record of a city called Glarnovia." and not script.queue
