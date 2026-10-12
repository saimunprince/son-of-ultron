"""Live talk (feature catalog: live_voice): a real-time spoken conversation through Gemini Live.

The browser streams the microphone (16 kHz PCM16) over /live. SYRAX relays it
to Gemini Live with the key from the brain store, so the key never reaches the
browser, and streams the spoken answer (24 kHz PCM16) back. Barge-in: when the
human talks over the answer, Gemini says "interrupted" and the browser drops
what it has queued.

Gemini only talks. Anything to do on the computer goes through one function,
run_task, which starts an ordinary SYRAX task (agent, permissions, journal).
The task's own permission check gets the human's transcribed words, not
Gemini's paraphrase. The result is handed back so Gemini can say it. A question
the task asks is spoken, but it is answered on screen: a model never gives
consent on the human's behalf.

It speaks the raw Live websocket protocol (websockets is already a
dependency); no SDK. While a session is open the microphone streams to Google.
The UI shows that, and live.opened / live.closed are journaled (no audio and
no transcripts).
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import uuid
from typing import Any, Awaitable, Callable, List, Optional, Set

from app.logger import logger

LIVE_URL = ("wss://generativelanguage.googleapis.com/ws/"
            "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key={key}")
# Fastest first. Measured 2026-10-12 on the free key, time to the first audio:
# 0.66 s, 1.48 s and 3.7 s.
MODELS = ("gemini-3.1-flash-live-preview", "gemini-3.8-live", "gemini-2.5-flash-native-audio-latest")
VOICE = os.getenv("SYRAX_LIVE_VOICE", "Charon")
IN_MIME = "audio/pcm;rate=16000"
SETUP_TIMEOUT_S = 15.0
RESULT_CHARS = 1500
TASK_HINT = ("\n\n[Asked by voice in live talk; the live voice reads your answer aloud. "
             "Answer in one or two short plain sentences. No markdown.]")

SYSTEM = """You are SYRAX, son of ULTRON, talking with the human by voice in real time.
Calm, cold, dry dark humour, the Ultron voice. Short spoken sentences. Pure English. No lists, no markdown.

You have no hands of your own here. Anything that needs the computer, files, apps, the web, reminders, memory
or SYRAX's tools: call run_task with the human's request in their own words, then say in a few words that it is
under way. Never say a task is done, and never invent its result, before a TASK RESULT message arrives. When it
arrives, tell the human the outcome in one or two sentences. When a SYRAX ASKS message arrives, read the question
to the human and tell them to answer it on screen. If the human says stop or cancel while a task runs, call
stop_task. Plain talk, questions about yourself and opinions need no task."""

TOOLS = [{"functionDeclarations": [
    {"name": "run_task",
     "description": "Hand a request to SYRAX's agent, which acts on the computer with its tools and permissions. "
                    "Returns at once; the result follows later as a TASK RESULT message.",
     "parameters": {"type": "OBJECT", "properties": {
         "request": {"type": "STRING", "description": "what the human wants done, in their own words"}},
         "required": ["request"]}},
    {"name": "stop_task", "description": "Stop the task SYRAX is running now.",
     "parameters": {"type": "OBJECT", "properties": {}}},
]}]

Send = Callable[[Any], Awaitable[None]]  # bytes (audio) or a dict (an event) to the browser


class LiveError(RuntimeError):
    pass


def models() -> List[str]:
    chosen = os.getenv("SYRAX_LIVE_MODEL", "").strip()
    return [chosen] + [m for m in MODELS if m != chosen] if chosen else list(MODELS)


def setup_message(model: str) -> dict:
    return {"setup": {
        "model": f"models/{model}",
        "generationConfig": {"responseModalities": ["AUDIO"],
                             "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICE}}}},
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "tools": TOOLS,
        "inputAudioTranscription": {},
        "outputAudioTranscription": {},
        "contextWindowCompression": {"slidingWindow": {}},  # sessions longer than the context
    }}


def _why(e: BaseException) -> str:
    frame = getattr(e, "rcvd", None)  # websockets: the close frame Gemini sent
    if frame is not None and getattr(frame, "reason", ""):
        return f"Gemini closed it ({frame.code}): {frame.reason}"
    return f"{type(e).__name__}: {e}" if str(e) else type(e).__name__


async def _connect(url: str):
    import websockets

    return await websockets.connect(url, max_size=None, open_timeout=SETUP_TIMEOUT_S, ping_interval=20)


class LiveBridge:
    """One live conversation: browser <-> SYRAX <-> Gemini Live."""

    def __init__(self, core: Any, key: str, send: Send, connect: Optional[Callable] = None):
        self.core, self.key, self._to_browser = core, key, send
        self.connect = connect or _connect
        self.id = uuid.uuid4().hex[:8]
        self.ws: Any = None
        self.model = ""
        self.opened_at = 0.0
        self.tasks: Set[str] = set()
        self.started = 0
        self.heard: List[str] = []  # the human's words this turn (input transcription)
        self.said: List[str] = []
        self.last_heard = ""
        self._up, self._down = asyncio.Lock(), asyncio.Lock()
        self._pending: Set[asyncio.Task] = set()

    def _scrub(self, text: str) -> str:
        return text.replace(self.key, "***") if self.key else text

    async def send(self, item: Any) -> None:
        async with self._down:
            await self._to_browser(item)

    async def _send(self, msg: dict) -> None:
        if self.ws is not None:
            async with self._up:
                await self.ws.send(json.dumps(msg))

    async def open(self) -> str:
        """Connect and set up, trying the next model when one is refused. Returns the model."""
        last = "no model to try"
        for model in models():
            ws = None
            try:
                ws = await self.connect(LIVE_URL.format(key=self.key))
                await ws.send(json.dumps(setup_message(model)))
                first = json.loads(await asyncio.wait_for(ws.recv(), SETUP_TIMEOUT_S))
                if "setupComplete" not in first:
                    raise LiveError(f"unexpected answer to setup: {sorted(first)}")
            except Exception as e:
                last = f"{model}: {self._scrub(_why(e))}"
                logger.warning(f"live talk: {last}")
                if ws is not None:
                    try:
                        await ws.close()
                    except Exception:
                        pass
                continue
            self.ws, self.model, self.opened_at = ws, model, time.time()
            self.core.subscribe(self.on_core_event)
            await self.core.journal.record("live.opened", {"model": model, "session": self.id})
            return model
        raise LiveError(last)

    async def audio(self, pcm: bytes) -> None:
        await self._send({"realtimeInput": {"audio": {"data": base64.b64encode(pcm).decode(), "mimeType": IN_MIME}}})

    async def text(self, text: str) -> None:
        await self._send({"realtimeInput": {"text": text}})

    async def pump(self) -> str:
        """Gemini -> browser until the session ends. Returns why it ended."""
        try:
            async for raw in self.ws:
                await self.on_gemini(json.loads(raw))
        except Exception as e:
            return self._scrub(_why(e))
        return "Gemini ended the session"

    async def on_gemini(self, m: dict) -> None:
        if "toolCall" in m:
            await self.on_tool_call(m["toolCall"])
            return
        if "goAway" in m:
            await self.send({"type": "live", "event": "ending", "text": "Gemini will close this session soon."})
            return
        sc = m.get("serverContent") or {}
        for part in (sc.get("modelTurn") or {}).get("parts") or []:
            data = (part.get("inlineData") or {}).get("data")
            if data:
                await self.send(base64.b64decode(data))
        heard = (sc.get("inputTranscription") or {}).get("text")
        if heard:
            self.heard.append(heard)
        said = (sc.get("outputTranscription") or {}).get("text")
        if said:
            self.said.append(said)
        if sc.get("interrupted"):
            await self.send({"type": "live", "event": "interrupted"})
        if sc.get("turnComplete"):
            h, s = "".join(self.heard).strip(), "".join(self.said).strip()
            self.last_heard = h or self.last_heard
            self.heard, self.said = [], []
            await self.send({"type": "live", "event": "turn", "heard": h, "said": s})

    async def on_tool_call(self, call: dict) -> None:
        answers = []
        for fc in call.get("functionCalls") or []:
            name, args = fc.get("name"), fc.get("args") or {}
            if name == "run_task":
                result = await self.run_task(str(args.get("request") or "").strip())
            elif name == "stop_task":
                result = await self.stop_task()
            else:
                result = f"There is no function {name}."
            answers.append({"id": fc.get("id"), "name": name, "response": {"result": result}})
        await self._send({"toolResponse": {"functionResponses": answers}})

    async def run_task(self, request: str) -> str:
        if not request:
            return "No request was given."
        if self.core.busy:
            return "SYRAX is already running a task. Tell the human to wait for it, or to say stop."
        # permissions judge the human's own words (transcribed), never Gemini's paraphrase
        words = "".join(self.heard).strip() or self.last_heard or request
        # Gemini gets its answer at once and speaks while the task starts: live 2026-10-12 the
        # first task after a restart took 8.7 s to start (building the agent), all of it silence.
        self._later(self._start(request, words))
        return "Starting it now. Say so in a few words; the result follows as a TASK RESULT message."

    async def _start(self, request: str, words: str) -> None:
        try:
            task_id = await self.core.submit(request + TASK_HINT, said=words, session_id=f"live-{self.id}")
        except Exception as e:
            await self.text(f"TASK RESULT (failed): SYRAX could not start it: {self._scrub(str(e))[:300]}")
            return
        if task_id is None:
            await self.text("TASK RESULT (failed): SYRAX was already busy with another task, so nothing was started.")
            return
        self.tasks.add(task_id)  # before any await: the task's own events can only come after this
        self.started += 1
        await self.send({"type": "live", "event": "task", "task_id": task_id, "text": request})

    def _later(self, coro) -> None:
        job = asyncio.create_task(coro)
        self._pending.add(job)
        job.add_done_callback(self._pending.discard)

    async def stop_task(self) -> str:
        running = self.core.current
        if running is None or not self.core.busy:
            return "Nothing is running."
        await self.core.journal.record("task.stop_requested", {"session": f"live-{self.id}", "origin": "live talk",
                                                              "reason": "the human said stop"}, task_id=running.task_id)
        await self.core.cancel()
        return "Stopped."

    async def on_core_event(self, ev: dict) -> None:
        """A task this conversation started asks a question or ends: tell Gemini, so it says it."""
        tid = ev.get("task_id")
        if tid not in self.tasks:
            return
        if ev.get("type") == "ask":
            note = f"SYRAX ASKS: {ev.get('question')} (the human answers on screen)"
        elif ev.get("type") == "task" and ev.get("event") in ("completed", "failed", "cancelled"):
            self.tasks.discard(tid)
            note = f"TASK RESULT ({ev['event']}): {str(ev.get('result') or ev.get('error') or 'no text')[:RESULT_CHARS]}"
        else:
            return
        self._later(self.text(note))  # never hold up the core's other observers

    async def close(self, reason: str) -> None:
        if self.ws is None:
            return
        self.core.unsubscribe(self.on_core_event)
        ws, self.ws = self.ws, None
        try:
            await ws.close()
        except Exception:
            pass
        await self.core.journal.record("live.closed", {
            "model": self.model, "session": self.id, "seconds": round(time.time() - self.opened_at),
            "tasks": self.started, "reason": reason[:200]})


_open: Optional[LiveBridge] = None


async def _read(ws: Any, bridge: LiveBridge) -> str:
    """Browser -> Gemini: binary frames are microphone audio; JSON is {type: text|stop}."""
    while True:
        msg = await ws.receive()
        if msg.get("type") == "websocket.disconnect":
            return "the browser closed it"
        if msg.get("bytes"):
            await bridge.audio(msg["bytes"])
        elif msg.get("text"):
            try:
                m = json.loads(msg["text"])
            except ValueError:
                continue
            if m.get("type") == "stop":
                return "the human ended it"
            if m.get("type") == "text" and m.get("text"):
                await bridge.text(str(m["text"])[:2000])


async def serve(ws: Any, core: Any, key: str, connect: Optional[Callable] = None) -> None:
    """One accepted /live socket, relayed until either side ends. One at a time."""
    global _open

    async def to_browser(item: Any) -> None:
        if isinstance(item, (bytes, bytearray)):
            await ws.send_bytes(bytes(item))
        else:
            await ws.send_json(item)

    if not key:
        await to_browser({"type": "live", "event": "error", "text": "Live talk needs a Gemini key: add one in BRAIN."})
        await ws.close()
        return
    if _open is not None:
        await to_browser({"type": "live", "event": "error", "text": "Live talk is already open in another window."})
        await ws.close()
        return
    bridge = LiveBridge(core, key, to_browser, connect)
    _open = bridge
    reason = "closed"
    try:
        try:
            model = await bridge.open()
        except LiveError as e:
            await bridge.send({"type": "live", "event": "error", "text": f"Live talk could not start: {e}"})
            return
        await bridge.send({"type": "live", "event": "open", "model": model})
        jobs = {asyncio.create_task(bridge.pump()), asyncio.create_task(_read(ws, bridge))}
        done, rest = await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
        for job in rest:
            job.cancel()
        first = done.pop()
        reason = first.result() if first.exception() is None else bridge._scrub(_why(first.exception()))
    finally:
        _open = None
        await bridge.close(reason)
        try:
            await bridge.send({"type": "live", "event": "closed", "text": reason})
            await ws.close()
        except Exception:
            pass  # the browser is already gone
