"""SYRAX WebSocket server.

Run from the backend directory:
    .venv/bin/python -m syrax.server

Protocol (JSON over ws://HOST:PORT/ws)
  client -> server: task {text, voice?} | answer {text} | stop | reset | ping |
                    history {limit?} | task_events {task_id} | resume {task_id} |
                    verifications {limit?} | self_model {section?} |
                    objectives {limit?} | objective_add {goal, reason?, priority?} |
                    task_detail {task_id} | replay {since?, until?} |
                    autonomy {enabled?} | cycle_now |
                    brains_get | brains_save {providers, order} |
                    brain_models {id, api_key?} | brain_test {id}
  server -> client: hello {name, tools, interrupted, running, recent} | state |
                    user | think | tool_start | tool_result | ask | final |
                    task {event} | checkpoint | recovery {event} | verification |
                    history | task_events | verifications | self_model |
                    objectives | autonomy_status | autonomy {event} | objective {event} | cycle {event} |
                    task_detail | replay |
                    reflection {event} |
                    notice | error | pong | brain | brains | brain_models | brain_test

Sessions are observers: the task runs in ``syrax.core`` and continues when the
browser disconnects. Journaled events (think, tool_*, ask, answer, final, brain
failover/answered, task/checkpoint/recovery/verification) are written to the
durable journal first and fanned out to every connected session; ``state``,
``notice``, ``error``, panel replies and the ``user`` echo are direct.
"""

import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.logger import logger

from syrax import browser, voice
from syrax.brains import PROVIDERS, get_router
from syrax.core import get_core
from syrax.journal import JournalError, get_journal

VOICE_HINT = (
    "\n\n[Spoken aloud by voice. Answer in one or two short spoken English "
    "sentences. No markdown, no lists, no code unless asked.]"
)

HOST = os.getenv("SYRAX_HOST", "127.0.0.1")
PORT = int(os.getenv("SYRAX_PORT", "8765"))
ALLOWED_ORIGINS = {
    o.strip()
    for o in os.getenv(
        "SYRAX_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if o.strip()
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    journal = get_journal()  # opens the durable journal and runs crash recovery
    for r in journal.recovered:
        logger.warning(
            f"recovered interrupted task {r['task_id']} at step {r['last_step']} "
            f"({r['last_stage']}): {r['recovery']['state']}"
        )
    core = get_core()
    for tid in await core.auto_resume():
        logger.warning(f"auto-resumed task {tid}")
    if core.autonomy.enabled:
        core.autonomy.start()
        logger.info("autonomy loop started")
    logger.info(f"SYRAX online at ws://{HOST}:{PORT}/ws")
    # Warm the local ear in the background so the first voice command is fast.
    warm = asyncio.create_task(asyncio.to_thread(_warm_whisper))
    yield
    warm.cancel()
    await core.shutdown()
    browser.shutdown()
    journal.close()


def _warm_whisper() -> None:
    if os.getenv("SYRAX_DISABLE_WHISPER_WARMUP"):
        return
    try:
        voice.local_whisper.load()
    except Exception as e:
        logger.error(f"Whisper warm-up failed: {e}")


app = FastAPI(title="SYRAX", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(ALLOWED_ORIGINS),
    allow_methods=["GET", "POST"],
    allow_headers=["content-type"],
)


def _check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin not in ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="origin not allowed")


@app.post("/stt")
async def stt(request: Request):
    _check_origin(request)
    audio = await request.body()
    if len(audio) > voice.MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="audio too long")
    groq_key = get_router().store.key("groq") or None
    try:
        return await voice.transcribe(audio, groq_key)
    except Exception as e:
        logger.exception("STT failed")
        raise HTTPException(status_code=500, detail=f"speech recognition failed: {str(e)[:200]}")


@app.post("/tts")
async def tts(request: Request):
    _check_origin(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="json body with 'text' required")
    text = str((body or {}).get("text") or "")[:4000]
    started = asyncio.get_running_loop().time()
    try:
        audio = await voice.synthesize(text)
    except Exception as e:
        logger.warning(f"TTS failed: {e}")
        raise HTTPException(status_code=502, detail="tts unavailable")
    ms = int((asyncio.get_running_loop().time() - started) * 1000)
    logger.info(f"TTS {len(audio)} bytes in {ms}ms: {text[:60]!r}")
    return Response(content=audio, media_type="audio/mpeg")


@app.get("/voice")
async def voice_status():
    return {
        "tts_voice": voice.TTS_VOICE,
        "stt": "groq" if get_router().store.key("groq") else f"whisper-{voice.local_whisper.size}",
        "whisper": voice.local_whisper.status,
    }


@app.get("/self")
async def self_model(section: str = "summary"):
    """Read-only self-model (evidence-based). ?section=summary|identity|structure|runtime|behavior|capabilities|weaknesses|all"""
    try:
        return await asyncio.to_thread(get_core().selfmodel.snapshot, section)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/health")
async def health():
    router = get_router()
    return {"name": "SYRAX", "status": "online", "brain": router.active}


class Session:
    """One WebSocket connection: observes the core, routes commands to it."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.id = uuid.uuid4().hex[:12]
        self.core = get_core()
        self.closed = False
        self._lock = asyncio.Lock()
        self.aux: set = set()

    def spawn(self, coro) -> None:
        """Run slow side jobs (model lists, brain tests) off the receive loop."""
        t = asyncio.create_task(coro)
        self.aux.add(t)
        t.add_done_callback(self.aux.discard)

    async def send(self, event: dict) -> None:
        if self.closed:
            return
        async with self._lock:
            try:
                await self.ws.send_json(event)
            except Exception:
                self.closed = True

    async def boot(self) -> None:
        await self.send({"type": "state", "state": "booting"})
        agent = await self.core.ensure_agent()
        snap = self.core.snapshot()
        self.core.subscribe(self.send)
        await self.send(
            {
                "type": "hello",
                "name": "SYRAX",
                "tools": sorted(agent.available_tools.tool_map.keys()),
                "interrupted": snap["interrupted"],
                "running": snap["running"],
                "recent": snap["recent"],
                "autonomy": await asyncio.to_thread(self.core.autonomy.status),
            }
        )
        await self.send({"type": "brains", **get_router().describe()})
        if snap["running"]:
            # Reconnect while a task runs: replay what happened so far, then the live state.
            tid = snap["running"]["task_id"]
            events = await asyncio.to_thread(get_journal().events, tid)
            await self.send({"type": "task_events", "task_id": tid, "events": events})
            await self.send({"type": "state", **snap["state"]})
        else:
            await self.send({"type": "state", "state": "idle"})

    async def handle(self, msg: dict) -> None:
        kind = msg.get("type")
        text = str(msg.get("text") or "").strip()
        journal = get_journal()

        if kind == "ping":
            await self.send({"type": "pong"})
        elif kind == "task":
            if not text:
                return
            if self.core.busy:
                await self.send(
                    {"type": "notice", "text": "Already executing. Stop it first."}
                )
                return
            await self.core.broadcast({"type": "user", "text": text, "voice": bool(msg.get("voice"))})
            request = text + VOICE_HINT if msg.get("voice") else text
            await self.core.submit(request, said=text, session_id=self.id)
        elif kind == "answer":
            if not await self.core.answer(text, session_id=self.id):
                await self.send({"type": "notice", "text": "No pending question."})
        elif kind == "stop":
            await self.core.cancel()
        elif kind == "reset":
            await self.core.reset()
            await self.send({"type": "notice", "text": "Memory wiped."})
        elif kind == "history":
            limit = _limit(msg.get("limit"), 20)
            tasks = await asyncio.to_thread(journal.tasks, limit)
            await self.send({"type": "history", "tasks": tasks})
        elif kind == "task_events":
            tid = str(msg.get("task_id") or "")
            events = await asyncio.to_thread(journal.events, tid)
            await self.send({"type": "task_events", "task_id": tid, "events": events})
        elif kind == "task_detail":
            tid = str(msg.get("task_id") or "")
            detail = await asyncio.to_thread(journal.task_detail, tid)
            if detail is None:
                await self.send({"type": "notice", "text": f"Unknown task {tid}."})
            else:
                await self.send({"type": "task_detail", "task_id": tid, **detail})
        elif kind == "replay":
            try:
                since = float(msg.get("since") or (time.time() - 86400))
                until = float(msg["until"]) if msg.get("until") is not None else None
            except (TypeError, ValueError):
                since, until = time.time() - 86400, None
            events = await asyncio.to_thread(journal.events_between, since, until)
            await self.send({"type": "replay", "since": since, "until": until, "events": events})
        elif kind == "verifications":
            limit = _limit(msg.get("limit"), 20)
            rows = await asyncio.to_thread(journal.verifications, limit)
            await self.send({"type": "verifications", "verifications": rows})
        elif kind == "self_model":
            section = str(msg.get("section") or "summary")
            try:
                snap = await asyncio.to_thread(self.core.selfmodel.snapshot, section)
                await self.send({"type": "self_model", "section": section, **snap})
            except ValueError as e:
                await self.send({"type": "error", "message": str(e)})
        elif kind == "objectives":
            limit = _limit(msg.get("limit"), 50)
            rows = await asyncio.to_thread(journal.objectives, limit)
            await self.send({"type": "objectives", "objectives": rows})
        elif kind == "objective_add":
            goal = str(msg.get("goal") or "").strip()
            if not goal:
                await self.send({"type": "notice", "text": "Objective needs a goal."})
                return
            try:
                priority = max(1, min(int(msg.get("priority") or 3), 9))
            except (TypeError, ValueError):
                priority = 3
            await journal.add_objective(goal, str(msg.get("reason") or "") or None, priority, "human")
        elif kind == "autonomy":
            if "enabled" in msg:
                on = bool(msg.get("enabled"))
                await self.core.autonomy.set_enabled_async(on)
                if on:
                    self.core.autonomy.start()
                else:
                    await self.core.autonomy.stop()
            await self.send({"type": "autonomy_status", **await asyncio.to_thread(self.core.autonomy.status)})
        elif kind == "cycle_now":
            if self.core.busy:
                await self.send({"type": "notice", "text": "Already executing. Stop it first."})
                return
            self.spawn(self._cycle())
        elif kind == "resume":
            tid = str(msg.get("task_id") or "")
            try:
                problem = await self.core.resume(tid, session_id=self.id)
            except JournalError as e:
                problem = str(e)
            if problem:
                await self.send({"type": "notice", "text": problem})
        elif kind == "brains_get":
            await self.send({"type": "brains", **get_router().describe()})
        elif kind == "brains_save":
            router = get_router()
            router.update(msg.get("providers") or {}, msg.get("order"))
            await self.send({"type": "brains", **router.describe()})
        elif kind == "brain_models":
            pid = str(msg.get("id") or "")
            if pid in PROVIDERS:
                key = msg.get("api_key")
                self.spawn(self._models(pid, str(key).strip() if key else None))
        elif kind == "brain_test":
            pid = str(msg.get("id") or "")
            if pid in PROVIDERS:
                self.spawn(self._test(pid))
        else:
            await self.send({"type": "error", "message": f"Unknown message: {kind}"})

    async def _cycle(self) -> None:
        rep = await self.core.autonomy.run_once(force=True)
        await self.core.broadcast({"type": "autonomy_status", **await asyncio.to_thread(self.core.autonomy.status)})
        if rep.outcome != "RAN":
            await self.send({"type": "notice", "text": f"Cycle {rep.outcome.lower()}: {rep.reason}"})

    async def _models(self, pid: str, key: Optional[str]) -> None:
        router = get_router()
        try:
            models = await router.list_models(pid, key)
            await self.send({"type": "brain_models", "id": pid, "models": models})
        except Exception as e:
            await self.send(
                {"type": "brain_models", "id": pid, "models": [], "error": router._reason(e)}
            )

    async def _test(self, pid: str) -> None:
        router = get_router()
        result = await router.test(pid)
        await self.send({"type": "brain_test", **result})
        await self.send({"type": "brains", **router.describe()})

    async def close(self) -> None:
        """Detach. The running task, if any, keeps going in the core."""
        self.core.unsubscribe(self.send)
        for t in list(self.aux):
            t.cancel()
        self.closed = True


def _limit(value, default: int) -> int:
    try:
        return max(1, min(int(value or default), 200))
    except (TypeError, ValueError):
        return default


def _explain(e: Exception) -> str:
    cause = e.__cause__ or e
    text = str(cause) or cause.__class__.__name__
    if "api_key" in text.lower() or "401" in text or "authentication" in text.lower():
        return "LLM authentication failed. Check api_key in backend/config/config.toml."
    return text[:500]


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    origin = ws.headers.get("origin")
    if origin and origin not in ALLOWED_ORIGINS:
        logger.warning(f"Rejected WebSocket from origin {origin}")
        await ws.close(code=1008)
        return

    await ws.accept()
    session = Session(ws)
    try:
        await session.boot()
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                await session.send({"type": "error", "message": "Malformed message ignored."})
                continue
            if not isinstance(msg, dict):
                continue
            try:
                await session.handle(msg)
            except Exception as e:  # one bad command must not kill the session
                logger.exception("SYRAX command failed")
                await session.send({"type": "error", "message": _explain(e)})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.exception("SYRAX session error")
        await session.send({"type": "error", "message": _explain(e)})
    finally:
        await session.close()


def main() -> None:
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
