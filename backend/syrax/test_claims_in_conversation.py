"""Review 2026-10-27: CLAIM and WORLD_CLAIM caught ordinary answers in human conversations, and CLAIM_FALLBACK then
replaced them: "check config.yaml, don't change it" -> "I have not modified anything. The port is 8080." lost the
port and ended PARTIAL. A negation, a word that names a kind of thing, a dated or (in a conversation that asks for no
change) any passive fact, and a text the brain wrote are no claims; the live claims the rules cite still are."""

import asyncio

import pytest

from syrax.agent import CLAIM, CLAIM_FALLBACK, WORLD_CLAIM, WORLD_NUDGE
from syrax.test_bridge import ORIGIN, TestClient, boot, core_mod, get_journal, reply, script, server  # noqa: F401

NOT_CLAIMS = [
    "Fixed-point arithmetic stores numbers as scaled integers.",
    "Implemented in Rust, ripgrep is faster than grep.",
    "The law has been changed since 2020.",
    "I have not changed anything.",
    "I never modified it.",
    "I've never modified that file.",
    "I have not modified anything. The port is 8080.",
]
NOT_WORLD = [
    "Here's a short poem I wrote for you:\nRoses are red.",
    "I created a haiku:\nold pond, a frog jumps in",
    "I wrote you a little poem about rain.",
    "The rule has been removed since 2019.",
]
STILL_CLAIMS = [  # the live cases the rules cite
    "Fixed the quality regression.",
    "Fixed task quality regression by ensuring prompt alignment.",
    "Fixed in commit 437d802.",
    "I have updated fixed.txt.",
    "I have implemented the change.",
    "The bug has been fixed.",
]
STILL_WORLD = [
    "The file has been deleted. No further action needed.",
    "I deleted old.log.",
    "I've created the file at C:/x/todo.md.",
    "I wrote the poem to poem.txt.",
    "I created a story file in the notes folder.",
    "I have written the report.",
]


@pytest.mark.parametrize("text", NOT_CLAIMS)
def test_negations_kinds_and_dated_facts_are_not_claims(text):
    assert not CLAIM.search(text) and not WORLD_CLAIM.search(text)


@pytest.mark.parametrize("text", NOT_WORLD)
def test_a_text_the_brain_wrote_is_not_a_world_change(text):
    assert not WORLD_CLAIM.search(text)


@pytest.mark.parametrize("text", STILL_CLAIMS)
def test_live_change_claims_are_still_caught(text):
    assert CLAIM.search(text)


@pytest.mark.parametrize("text", STILL_WORLD)
def test_live_world_claims_are_still_caught(text):
    assert WORLD_CLAIM.search(text)


def test_change_asked_reads_the_request():
    from syrax.agent import CHANGE_ASKED

    assert CHANGE_ASKED.search("Delete the file C:/x/old.log.") and CHANGE_ASKED.search("add a test for task durations")
    assert not CHANGE_ASKED.search("Does macOS still ship Python 2?")


def run(text, kind="conversation"):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()

    async def go():
        tid = await core.submit(text, said=text, session_id=None, kind=kind)
        await core.wait()
        return tid

    tid = asyncio.run(go())
    return core.journal.task(tid), [e for e in get_journal().events(tid) if e["type"] == "claim.rejected"]


def test_an_honest_not_modified_answer_keeps_its_content(script):
    script.queue = [reply("I have not modified anything. The port is 8080.")]
    task, rejected = run("check config.yaml, don't change it: which port does it set?")
    assert task["result"] == "I have not modified anything. The port is 8080." and task["status"] == "SUCCESS"
    assert rejected == [] and not script.queue


def test_a_passive_fact_answers_a_question(script):
    script.queue = [reply("Python 2 has been removed from macOS; use python3.")]
    task, rejected = run("Does macOS still ship Python 2?")
    assert task["result"] == "Python 2 has been removed from macOS; use python3." and rejected == []


def test_a_poem_is_not_sent_back(script):
    poem = "Here's a short poem I wrote for you:\nRain on the roof,\nsoft as a sigh."
    script.queue = [reply(poem)]
    task, rejected = run("tell me a short poem about rain")
    assert task["result"] == poem and rejected == []
    assert not any(WORLD_NUDGE in str(getattr(m, "content", "")) for msgs in script.seen for m in msgs)


def test_a_passive_claim_after_a_change_request_is_still_held(script, tmp_path):
    target = tmp_path / "old.log"
    target.write_text("stale\n")
    script.queue = [reply("The file has been deleted."), reply("The file has been deleted."),
                    reply("The file has been deleted.")]
    task, rejected = run(f"Delete the file {target}.")
    assert target.exists() and task["result"] == CLAIM_FALLBACK and len(rejected) == 2
