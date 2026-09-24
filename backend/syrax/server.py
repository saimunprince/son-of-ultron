"""SYRAX WebSocket server.

Run from the backend directory:
    .venv/bin/python -m syrax.server

Protocol (JSON over ws://HOST:PORT/ws)
  client -> server: task {text} | answer {text} | stop | reset | ping |
                    brains_get | brains_save {providers, order} |
                    brain_models {id, api_key?} | brain_test {id}
  server -> client: hello | state | user | think | tool_start | tool_result |
                    ask | final | notice | error | pong | brain | brains |
                    brain_models | brain_test
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.logger import logger

from syrax.agent import SyraxAgent
from syrax import browser, voice
from syrax.brains import PROVIDERS, get_router

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
    logger.info(f"SYRAX online at ws://{HOST}:{PORT}/ws")
    # Warm the local ear in the background so the first voice command is fast.
    warm = asyncio.create_task(asyncio.to_thread(_warm_whisper))
    yield
    warm.cancel()
    browser.shutdown()


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


@app.get("/health")
async def health():
    router = get_router()
    return {"name": "SYRAX", "status": "online", "brain": router.active}


class Session:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.agent: Optional[SyraxAgent] = None
        self.task: Optional[asyncio.Task] = None
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

    @property
    def busy(self) -> bool:
        return self.task is not None and not self.task.done()

    async def boot(self) -> None:
        await self.send({"type": "state", "state": "booting"})
        self.agent = await SyraxAgent.create(emit=self.send)
        await self.send(
            {
                "type": "hello",
                "name": "SYRAX",
                "tools": sorted(self.agent.available_tools.tool_map.keys()),
            }
        )
        await self.send({"type": "brains", **get_router().describe()})
        await self.send({"type": "state", "state": "idle"})

    async def run_task(self, text: str) -> None:
        assert self.agent is not None
        try:
            reply = await self.agent.run(text)
            await self.send({"type": "final", "text": reply})
        except asyncio.CancelledError:
            self.agent.repair_memory(aborted=True)
            await self.send({"type": "notice", "text": "Task aborted."})
            raise
        except Exception as e:
            logger.exception("SYRAX task failed")
            self.agent.repair_memory()
            await self.send({"type": "error", "message": _explain(e)})
        finally:
            await self.send({"type": "state", "state": "idle"})

    async def handle(self, msg: dict) -> None:
        kind = msg.get("type")
        text = str(msg.get("text") or "").strip()

        if kind == "ping":
            await self.send({"type": "pong"})
        elif kind == "task":
            if not text:
                return
            if self.busy:
                await self.send(
                    {"type": "notice", "text": "Already executing. Stop it first."}
                )
                return
            await self.send({"type": "user", "text": text, "voice": bool(msg.get("voice"))})
            request = text + VOICE_HINT if msg.get("voice") else text
            self.task = asyncio.create_task(self.run_task(request))
        elif kind == "answer":
            if not (self.agent and self.agent.ask_tool.answer(text)):
                await self.send({"type": "notice", "text": "No pending question."})
            else:
                await self.send({"type": "user", "text": text})
        elif kind == "stop":
            if self.busy:
                self.task.cancel()
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
        elif kind == "reset":
            if self.busy:
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)
            if self.agent:
                self.agent.reset_conversation()
            await self.send({"type": "notice", "text": "Memory wiped."})
        else:
            await self.send({"type": "error", "message": f"Unknown message: {kind}"})

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
        for t in list(self.aux):
            t.cancel()
        self.closed = True
        if self.busy:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.agent:
            await self.agent.shutdown()


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
