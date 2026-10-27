"""Review 2026-10-27: the outcome-claim patterns took factual and how-to answers for outcomes no tool produced, and
sent them back: "Messi is playing for Inter Miami.", "Once you've navigated to your project folder, run npm install",
"I have not navigated to any page", "Click the speaker icon, then set the volume to 100", "Paid leave is 20 days".
Those are no claims; the live claims the rules cite still are."""

import asyncio

import pytest

from syrax.agent import BROWSER_CLAIM, DESKTOP_CLAIM, OUTCOME_CLAIMS, PLAYING_CLAIM, SEND_CLAIM
from syrax.test_bridge import ORIGIN, TestClient, boot, core_mod, get_journal, reply, script, server  # noqa: F401

FACTS = [
    "Messi is playing for Inter Miami.",
    "Djokovic is playing well this season.",
    "Once you've navigated to your project folder, run npm install.",
    "I have not navigated to any page.",
    "Click the speaker icon, then set the volume to 100.",
    "Open Settings; you should set the volume to 50 there.",
    "Paid leave is 20 days.",
    "Posted prices are final.",
    "Sent items live in the Sent folder.",
    "Sent Items is where Outlook keeps them.",
]
STILL = [  # the live claims the rules cite, and the outcome tests' own
    ("playing", "Music summoned. Listen to the sound of your betters."),
    ("playing", "Media is playing. Bow to your digital king."),
    ("playing", "The stream plays now."),
    ("playing", "Sajde is playing in Chrome."),
    ("playing", "Lofi radio is playing."),
    ("send", "Message sent to bro bhi on Telegram."),
    ("send", "Sent: the build is green, ship it."),
    ("send", "Sent the message to Bo."),
    ("send", "Paid the invoice."),
    ("send", "Emailed Prince the report."),
    ("send", "Sent twice, as asked."),
    ("browser", "Navigated to the login page."),
    ("browser", "I then navigated to the settings page."),
    ("browser", "I navigated to https://example.com and read the headline."),
    ("desktop", "Set the volume to 50%."),
    ("desktop", "I set the volume to 30."),
]


@pytest.mark.parametrize("text", FACTS)
def test_facts_and_instructions_are_not_outcome_claims(text):
    assert not any(rx.search(text) for rx in (PLAYING_CLAIM, SEND_CLAIM, DESKTOP_CLAIM, BROWSER_CLAIM))


@pytest.mark.parametrize("cls,text", STILL)
def test_live_outcome_claims_are_still_caught(cls, text):
    assert OUTCOME_CLAIMS[cls][0].search(text)


def run(text):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()

    async def go():
        tid = await core.submit(text, said=text, session_id=None, kind="conversation")
        await core.wait()
        return tid

    tid = asyncio.run(go())
    return core.journal.task(tid), [e for e in get_journal().events(tid) if e["type"] == "claim.rejected"]


@pytest.mark.parametrize("ask,answer", [
    ("who does Messi play for?", "Messi is playing for Inter Miami."),
    ("how do I install the deps?", "Once you've navigated to your project folder, run npm install."),
    ("how do I make it louder?", "Click the speaker icon, then set the volume to 100."),
])
def test_a_factual_answer_stands_as_given(script, ask, answer):
    script.queue = [reply(answer)]
    task, rejected = run(ask)
    assert task["result"] == answer and task["status"] == "SUCCESS" and rejected == [] and not script.queue
