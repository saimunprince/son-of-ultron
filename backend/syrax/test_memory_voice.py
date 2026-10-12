"""The memory panel and the voice picker (feature catalog): the human sees
every remembered fact and forgets one by its id; the voice is picked from a
fixed English list, kept in the journal, and used by /tts."""

import pytest

from syrax import voice
from syrax.memory import get_memory
from syrax.test_bridge import ORIGIN, TestClient, boot, get_journal, recv_until, script, server  # noqa: F401


def test_the_panel_lists_and_forgets_by_id(script):
    m = get_memory()
    m.remember("Prince likes his tea without sugar")
    m.remember("The office opens at nine")
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "memories"})
        got, _ = recv_until(ws, "memories")
        texts = {f["text"]: f["id"] for f in got["facts"]}
        assert {"Prince likes his tea without sugar", "The office opens at nine"} <= set(texts)
        ws.send_json({"type": "memory_forget", "id": texts["The office opens at nine"]})
        note, _ = recv_until(ws, "notice")
        assert note["text"] == "Forgot: The office opens at nine"
        got, _ = recv_until(ws, "memories")
        assert [f["text"] for f in got["facts"] if "office" in f["text"]] == []
        ws.send_json({"type": "memory_forget", "id": "everything"})  # only an id is accepted here
        note, _ = recv_until(ws, "notice")
        assert note["text"].startswith("No remembered fact") and len(get_memory().facts()) >= 1


def test_the_voice_is_picked_kept_and_used(script, monkeypatch):
    used = []

    async def fake(text):
        used.append(voice.ACTIVE_VOICE)
        return b"ID3"

    monkeypatch.setattr(voice, "ACTIVE_VOICE", None)  # restored after the test: the pick does not leak
    monkeypatch.setattr(voice, "synthesize", fake)
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        hello, _ = recv_until(ws, "hello")
        assert hello["voice"] == {"current": voice.TTS_VOICE, "voices": voice.VOICES}
        ws.send_json({"type": "voice_set", "voice": "en-GB-RyanNeural"})
        st, _ = recv_until(ws, "voice_status")
        assert st["current"] == "en-GB-RyanNeural"
        ws.send_json({"type": "voice_set", "voice": "bn-BD-PradeepNeural"})
        note, _ = recv_until(ws, "notice")
        assert note["text"].startswith("unknown voice")
    assert get_journal().get_meta(voice.VOICE_KEY) == "en-GB-RyanNeural"
    r = TestClient(server.app).post("/tts", json={"text": "hello"}, headers=ORIGIN)
    assert r.status_code == 200 and used[-1] == "en-GB-RyanNeural"


def test_an_unknown_stored_voice_falls_back(monkeypatch):
    monkeypatch.setattr(voice, "ACTIVE_VOICE", None)
    class J:
        def get_meta(self, key):
            return "xx-Nobody"

    assert voice.current_voice(J()) == voice.TTS_VOICE and voice.current_voice(None) == voice.TTS_VOICE
    with pytest.raises(ValueError):
        voice.set_voice(J(), "xx-Nobody")
    assert voice.load_voice(J()) == voice.TTS_VOICE and voice.ACTIVE_VOICE == voice.TTS_VOICE
