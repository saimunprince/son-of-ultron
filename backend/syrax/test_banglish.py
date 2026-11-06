"""Live 2026-11-06: "tumi ki ki korte paro? 3 line e bolo" was answered in English. Banglish (Bengali in Latin
letters) is told by its small words, and a Banglish request whose answer is not Banglish is asked once again."""

import pytest

from syrax.claims import LANG_ASK_BANGLISH, LANG_ASK_EN, banglish
from syrax.journal import get_journal
from syrax.test_bridge import ORIGIN, TestClient, boot, drain_until_idle, reply, script, server  # noqa: F401


def ask(script, text, *answers):
    script.queue = [reply(a) for a in answers]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": text})
        drain_until_idle(ws)
    return get_journal().tasks()[0]["result"]


@pytest.mark.parametrize("text", ["tumi ki ki korte paro? 3 line e bolo", "ekhon koyta baje? ar Tokyo te koyta baje?",
                                  "amar volume koto ache?", "Downloads folder e koyta pdf file ache?"])
def test_banglish_requests(text):
    assert banglish(text)


@pytest.mark.parametrize("text", ["What is the capital of Japan?", "Delete the file /tmp/old.log.",
                                  "Is there a kite in the image?", "What is your age and the tin can's name?",
                                  "I can execute tasks on your computer, manage files."])
def test_english_is_not_banglish(text):
    assert not banglish(text)


def test_an_english_answer_to_banglish_is_asked_again_in_banglish(script):
    out = ask(script, "aj koto gorom ache?", "It is 31 degrees.", "Aj 31 degree gorom ache.")
    assert out == "Aj 31 degree gorom ache." and LANG_ASK_BANGLISH.split(":")[0] in str(script.seen[-1][-1].content)


def test_a_banglish_answer_is_kept(script):
    assert ask(script, "amar volume koto ache?", "Apanar volume 72% ache.") == "Apanar volume 72% ache." and not script.queue


def test_a_bengali_script_answer_to_banglish_is_not_forced_into_english(script):
    out = ask(script, "aj koto gorom ache?", "আজ ৩১ ডিগ্রি।")
    assert out == "আজ ৩১ ডিগ্রি।" and not script.queue
    assert all(LANG_ASK_EN.split(":")[0] not in str(m[-1].content) for m in script.seen)
