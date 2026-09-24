"""Voice endpoint tests. The real-audio test uses local Whisper (no network)."""

import io
import math
import os
import struct
import tempfile
import wave

os.environ.setdefault("OPENMANUS_DISABLE_BROWSER_USE", "1")
os.environ.setdefault("SYRAX_DISABLE_WHISPER_WARMUP", "1")
os.environ.setdefault("SYRAX_BRAINS_FILE", os.path.join(tempfile.mkdtemp(), "brains.json"))

from fastapi.testclient import TestClient  # noqa: E402

from syrax import server, voice  # noqa: E402

ORIGIN = {"origin": "http://localhost:3000"}


def tone_wav(seconds=0.5, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(3000 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(int(rate * seconds))))
    return buf.getvalue()


def test_speakable_strips_markdown_and_code():
    out = voice.speakable("**Done.** Here:\n```python\nprint(1)\n```\nSee `x` at https://a.b/c")
    assert "print" not in out and "*" not in out and "https" not in out
    assert "code is on screen" in out and "link on screen" in out


def test_hallucinations_dropped():
    assert voice._clean(" Thank you. ") == ""
    assert voice._clean("Open Gmail") == "Open Gmail"


def test_tts_endpoint(monkeypatch):
    async def fake(text):
        assert text == "hello"
        return b"ID3fake"

    monkeypatch.setattr(voice, "synthesize", fake)
    r = TestClient(server.app).post("/tts", json={"text": "hello"}, headers=ORIGIN)
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg" and r.content == b"ID3fake"


def test_voice_endpoints_reject_foreign_origin():
    c = TestClient(server.app)
    assert c.post("/tts", json={"text": "x"}, headers={"origin": "https://evil.example"}).status_code == 403
    assert c.post("/stt", content=b"x", headers={"origin": "https://evil.example"}).status_code == 403


def test_stt_prefers_groq_when_key_saved(monkeypatch):
    calls = []

    async def fake_groq(audio, key):
        calls.append(key)
        return "SYRAX open Gmail"

    monkeypatch.setattr(voice, "groq_transcribe", fake_groq)
    router = server.get_router()
    router.update({"groq": {"api_key": "gsk_test_key_1234"}}, None)
    try:
        r = TestClient(server.app).post("/stt", content=tone_wav(), headers={**ORIGIN, "content-type": "audio/wav"})
        assert r.status_code == 200
        assert r.json()["text"] == "SYRAX open Gmail" and r.json()["engine"] == "groq"
        assert calls == ["gsk_test_key_1234"]
    finally:
        router.update({"groq": {"api_key": ""}}, None)


def test_stt_local_whisper_on_real_speech():
    """Round trip: synthesize speech offline-free check via a pre-made sample if present."""
    sample = os.getenv("SYRAX_TEST_SPEECH")
    if not sample or not os.path.exists(sample):
        import pytest

        pytest.skip("set SYRAX_TEST_SPEECH to a speech file to run")
    audio = open(sample, "rb").read()
    r = TestClient(server.app).post("/stt", content=audio, headers={**ORIGIN, "content-type": "audio/wav"})
    assert r.status_code == 200
    assert "syrax" in r.json()["text"].lower()


def test_voice_task_gets_spoken_hint(monkeypatch):
    seen = []
    from syrax.brains import BrainRouter
    from openai.types.chat import ChatCompletionMessage

    async def fake(self, messages, **kw):
        seen.append(" ".join(str(getattr(m, "content", None) or "") for m in messages))
        return ChatCompletionMessage(role="assistant", content="Four.")

    monkeypatch.setattr(BrainRouter, "ask_tool", fake)
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        while ws.receive_json().get("state") != "idle":
            pass
        ws.send_json({"type": "task", "text": "two plus two", "voice": True})
        user = ws.receive_json()
        assert user == {"type": "user", "text": "two plus two", "voice": True}
        while True:
            e = ws.receive_json()
            if e["type"] == "final":
                break
    assert seen and "two plus two" in seen[0] and "Spoken aloud by voice" in seen[0]
