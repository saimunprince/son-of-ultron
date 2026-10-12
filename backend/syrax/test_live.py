"""Live talk (feature catalog: live_voice): the setup Gemini Live gets, the
next model when one is refused, audio both ways with barge-in, tasks that go
through SYRAX's own agent judged on the human's words, results and questions
spoken back, and the /live endpoint end to end. A fake Gemini stands in, so
there is no network and no key here."""

import asyncio
import base64
import json
import types

from fastapi.testclient import TestClient

from syrax import live, server
from syrax.journal import _GROUPED
from syrax.test_bridge import ORIGIN, get_journal, script  # noqa: F401


class Closed(Exception):
    def __init__(self, reason):
        super().__init__("closed")
        self.rcvd = types.SimpleNamespace(code=1011, reason=reason)


class FakeGemini:
    def __init__(self, messages=(), fail=None):
        self.sent, self.closed, self.fail, self.messages = [], False, fail, list(messages)
        self.queue = None

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    async def recv(self):
        if self.fail:
            raise self.fail
        return json.dumps({"setupComplete": {}})

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.queue is None:
            self.queue = asyncio.Queue()
            for m in self.messages:
                self.queue.put_nowait(m)
        m = await self.queue.get()
        if m is None:
            raise StopAsyncIteration
        return json.dumps(m)

    async def close(self):
        self.closed = True


class FakeJournal:
    def __init__(self):
        self.events = []

    async def record(self, kind, payload, task_id=None):
        self.events.append((kind, payload, task_id))


class FakeCore:
    def __init__(self, busy=False):
        self.journal, self.observers, self.busy, self.submits = FakeJournal(), [], busy, []
        self.current, self.cancelled = None, False

    def subscribe(self, cb):
        self.observers.append(cb)

    def unsubscribe(self, cb):
        self.observers.remove(cb)

    async def submit(self, goal, said=None, session_id=None, kind="conversation"):
        self.submits.append({"goal": goal, "said": said, "session": session_id})
        return "t1"

    async def cancel(self):
        self.cancelled = True


def connecting(*gems):
    pool, urls = list(gems), []

    async def connect(url):
        urls.append(url)
        return pool.pop(0)
    return connect, urls


def opened(core=None, gem=None):
    core, gem, out = core or FakeCore(), gem or FakeGemini(), []

    async def to_browser(item):
        out.append(item)
    connect, _ = connecting(gem)
    bridge = live.LiveBridge(core, "KEY123", to_browser, connect)
    asyncio.run(bridge.open())
    return bridge, core, gem, out


def test_the_setup_names_a_live_model_the_voice_the_tools_and_asks_for_transcripts():
    s = live.setup_message("gemini-3.1-flash-live-preview")["setup"]
    assert s["model"] == "models/gemini-3.1-flash-live-preview" and s["generationConfig"]["responseModalities"] == ["AUDIO"]
    assert s["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == live.VOICE
    assert [f["name"] for f in s["tools"][0]["functionDeclarations"]] == ["run_task", "stop_task"]
    assert "inputAudioTranscription" in s and "outputAudioTranscription" in s and "contextWindowCompression" in s
    assert "TASK RESULT" in live.SYSTEM and "on screen" in live.SYSTEM
    assert live.models()[0] == live.MODELS[0]


def test_a_refused_model_hands_over_to_the_next_and_the_key_never_shows(monkeypatch):
    core, out = FakeCore(), []
    good = FakeGemini()
    connect, urls = connecting(FakeGemini(fail=Closed("quota exceeded for KEY123")), good)

    async def to_browser(item):
        out.append(item)
    bridge = live.LiveBridge(core, "KEY123", to_browser, connect)
    assert asyncio.run(bridge.open()) == live.MODELS[1]
    assert urls[0].endswith("?key=KEY123") and good.sent[0]["setup"]["model"] == f"models/{live.MODELS[1]}"
    assert core.journal.events[-1][0] == "live.opened" and core.observers == [bridge.on_core_event]

    async def refused(url):
        return FakeGemini(fail=Closed("KEY123 is not valid"))
    bad = live.LiveBridge(FakeCore(), "KEY123", to_browser, refused)
    try:
        asyncio.run(bad.open())
        raise AssertionError("open should fail")
    except live.LiveError as e:
        assert "KEY123" not in str(e) and "*** is not valid" in str(e)


def test_audio_goes_up_and_comes_back_and_barge_in_is_passed_on():
    bridge, _, gem, out = opened()
    asyncio.run(bridge.audio(b"\x01\x02"))
    assert gem.sent[-1] == {"realtimeInput": {"audio": {"data": "AQI=", "mimeType": "audio/pcm;rate=16000"}}}
    pcm = base64.b64encode(b"\x00\x10" * 4).decode()
    asyncio.run(bridge.on_gemini({"serverContent": {"modelTurn": {"parts": [{"inlineData": {"mimeType": "audio/pcm;rate=24000", "data": pcm}}]}}}))
    asyncio.run(bridge.on_gemini({"serverContent": {"inputTranscription": {"text": "what time "}}}))
    asyncio.run(bridge.on_gemini({"serverContent": {"inputTranscription": {"text": "is it"}, "outputTranscription": {"text": "Late."}}}))
    asyncio.run(bridge.on_gemini({"serverContent": {"interrupted": True}}))
    asyncio.run(bridge.on_gemini({"serverContent": {"turnComplete": True}}))
    assert out == [b"\x00\x10" * 4, {"type": "live", "event": "interrupted"},
                   {"type": "live", "event": "turn", "heard": "what time is it", "said": "Late."}]


def test_a_task_goes_to_the_agent_on_the_humans_words_and_its_result_is_spoken():
    bridge, core, gem, out = opened()

    async def go():
        await bridge.on_gemini({"serverContent": {"inputTranscription": {"text": "delete notes.txt on my desktop"}}})
        await bridge.on_gemini({"toolCall": {"functionCalls": [{"id": "fc1", "name": "run_task", "args": {"request": "Remove the notes file"}}]}})
        await bridge.on_core_event({"type": "ask", "question": "Delete notes.txt?", "task_id": "t1"})
        await bridge.on_core_event({"type": "task", "event": "completed", "result": "Other task", "task_id": "t9"})
        await bridge.on_core_event({"type": "task", "event": "completed", "result": "Deleted notes.txt.", "task_id": "t1"})
        await asyncio.gather(*bridge._pending)
    asyncio.run(go())
    sub = core.submits[0]
    assert sub["goal"].startswith("Remove the notes file") and live.TASK_HINT in sub["goal"]
    assert sub["said"] == "delete notes.txt on my desktop" and sub["session"] == f"live-{bridge.id}"
    reply = next(m for m in gem.sent if "toolResponse" in m)["toolResponse"]["functionResponses"][0]
    assert reply["id"] == "fc1" and reply["name"] == "run_task" and reply["response"]["result"].startswith("Started.")
    spoken = [m["realtimeInput"]["text"] for m in gem.sent if "text" in m.get("realtimeInput", {})]
    assert spoken == ["SYRAX ASKS: Delete notes.txt? (the human answers on screen)", "TASK RESULT (completed): Deleted notes.txt."]
    assert {"type": "live", "event": "task", "task_id": "t1", "text": "Remove the notes file"} in out
    assert bridge.tasks == set() and bridge.started == 1


def test_a_busy_syrax_starts_nothing_and_stop_cancels_the_running_task():
    bridge, core, gem, _ = opened(FakeCore(busy=True))
    assert asyncio.run(bridge.run_task("open notepad")).startswith("SYRAX is already running") and not core.submits
    assert asyncio.run(bridge.run_task("")) == "No request was given."
    core.current = types.SimpleNamespace(task_id="t5")
    assert asyncio.run(bridge.stop_task()) == "Stopped." and core.cancelled
    assert core.journal.events[-1][:1] == ("task.stop_requested",) and core.journal.events[-1][2] == "t5"
    core.busy = False
    assert asyncio.run(bridge.stop_task()) == "Nothing is running."
    asyncio.run(bridge.close("the human ended it"))
    kind, payload, _ = core.journal.events[-1]
    assert kind == "live.closed" and payload["reason"] == "the human ended it" and gem.closed and not core.observers


def test_the_live_endpoint_relays_until_the_human_stops(script, monkeypatch):
    gem = FakeGemini(messages=[{"serverContent": {"outputTranscription": {"text": "Speak."}, "turnComplete": True}}])

    async def connect(url):
        return gem
    monkeypatch.setattr(live, "_connect", connect)
    monkeypatch.setattr("syrax.brains.get_router", lambda: types.SimpleNamespace(store=types.SimpleNamespace(key=lambda pid: "KEY123")))
    with TestClient(server.app).websocket_connect("/live", headers=ORIGIN) as ws:
        assert ws.receive_json() == {"type": "live", "event": "open", "model": live.MODELS[0]}
        assert ws.receive_json() == {"type": "live", "event": "turn", "heard": "", "said": "Speak."}
        ws.send_bytes(b"\x05\x06")
        ws.send_text(json.dumps({"type": "stop"}))
        assert ws.receive_json() == {"type": "live", "event": "closed", "text": "the human ended it"}
    assert {"realtimeInput": {"audio": {"data": "BQY=", "mimeType": "audio/pcm;rate=16000"}}} in gem.sent
    kinds = [e["type"] for e in get_journal().recent_events(30)]
    assert "live.opened" in kinds and "live.closed" in kinds and "live" in _GROUPED
    assert live._open is None


def test_no_key_or_a_second_window_gets_a_plain_error(script, monkeypatch):
    monkeypatch.setattr("syrax.brains.get_router", lambda: types.SimpleNamespace(store=types.SimpleNamespace(key=lambda pid: "")))
    with TestClient(server.app).websocket_connect("/live", headers=ORIGIN) as ws:
        assert ws.receive_json() == {"type": "live", "event": "error", "text": "Live talk needs a Gemini key: add one in BRAIN."}
    monkeypatch.setattr("syrax.brains.get_router", lambda: types.SimpleNamespace(store=types.SimpleNamespace(key=lambda pid: "K")))
    monkeypatch.setattr(live, "_open", object())
    with TestClient(server.app).websocket_connect("/live", headers=ORIGIN) as ws:
        assert ws.receive_json()["text"] == "Live talk is already open in another window."
