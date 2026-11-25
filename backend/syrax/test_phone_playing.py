"""Live 2026-11-23: a John Wick mix played on the phone (its screen read "0 minutes 38 seconds of 18 minutes"), and
the answer was still marked "Not verified": only the computer's media status counted as reading what plays."""

from syrax.claims import PHONE_PLAYING_READ, PLAYING_NOTE
from syrax.test_bridge import call, reply, script, server  # noqa: F401
from syrax.test_change_proof import run


def test_the_phone_player_reading():
    assert PHONE_PLAYING_READ.search("- [button] 0 minutes 38 seconds of 18 minutes 4 seconds at 654,768")
    assert PHONE_PLAYING_READ.search("- [button] Pause video at 654,400")
    assert PHONE_PLAYING_READ.search("- [button] 1 hours 2 minutes 5 seconds of 3 hours at 1,1")
    assert not PHONE_PLAYING_READ.search("- [button] 0 minutes 0 seconds of 18 minutes at 654,768")
    assert not PHONE_PLAYING_READ.search("- [text] Pause between sets is 2 minutes")


def test_a_phone_reading_of_a_playing_video_proves_it_plays(script, monkeypatch):
    from syrax import android

    async def ui():
        return [{"label": "0 minutes 38 seconds of 18 minutes 4 seconds", "kind": "button", "x": 654, "y": 768, "tap": True, "id": ""}]

    monkeypatch.setattr(android, "ui", ui)
    script.queue = [call("desktop", {"action": "phone", "value": "ui"}), reply("The John Wick mix is now playing on your phone.")]
    task, _ = run("now play john wick theme song")
    assert task["result"] == "The John Wick mix is now playing on your phone." and PLAYING_NOTE not in task["result"]
