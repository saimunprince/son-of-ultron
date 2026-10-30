"""Catalog language_follow (owner's decision delegated on 2026-10-30): the persona said "Pure English only", so a
question in Bengali script got an English answer. A request in Bengali script is now answered in Bengali script, asked
once if the brain answered in English; Latin-script Banglish stays English."""

from syrax.claims import LANG_ASK, bengali
from syrax.journal import get_journal
from syrax.prompt import SYRAX_PERSONA
from syrax.test_bridge import ORIGIN, TestClient, boot, drain_until_idle, reply, script, server  # noqa: F401


def test_bengali_script_is_told_apart_from_banglish():
    assert bengali("আজকের আবহাওয়া কেমন?")
    assert bengali("python_execute দিয়ে ফাইলটা পড়ো")
    assert not bengali("ajker abohawa kemon?") and not bengali("what is the weather")
    assert "Bengali script" in SYRAX_PERSONA and "Pure English only" not in SYRAX_PERSONA


def test_an_english_answer_to_a_bengali_request_is_asked_again_in_bengali(script):
    script.queue = [reply("It is 31 degrees."), reply("এখন ৩১ ডিগ্রি।")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "আজ কত গরম?"})
        drain_until_idle(ws)
    task = get_journal().tasks()[0]
    assert task["result"] == "এখন ৩১ ডিগ্রি।" and LANG_ASK.split(":")[0] in str(script.seen[-1][-1].content)


def test_banglish_and_english_are_not_asked(script):
    script.queue = [reply("It is 31 degrees.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "aj koto gorom?"})
        drain_until_idle(ws)
    assert get_journal().tasks()[0]["result"] == "It is 31 degrees." and not script.queue
