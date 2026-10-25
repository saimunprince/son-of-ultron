"""SYRAX WebSocket server.

Run from the backend directory:
    .venv/bin/python -m syrax.server

Protocol (JSON over ws://HOST:PORT/ws)
  client -> server: task {text, voice?, queue?} (queue: a request made while a task runs waits for it
                    instead of being refused) | queue | queue_cancel {task_id, note?} |
                    answer {text} | stop | reset | ping |
                    history {limit?} | task_events {task_id} | resume {task_id, force?, note?} |
                    verifications {limit?} | self_model {section?} |
                    objectives {limit?} | objective_add {goal, reason?, priority?, check?} | briefing {hours?} |
                    brief_check {test_path, test_code, files?, fix_diff?} |
                    brief_add {goal, test_path, test_code, files, fix_diff?, reason?, priority?} (repro.py proves the
                    test fails on a clean HEAD, then files a change_released objective pinned to it) |
                    hunt_add {summary, evidence: [str], module?, tasks?, priority?} (SYRAX hunts the code cause:
                    writes the test and the fix; the judge proves both and files the brief) |
                    objective_update {id, status, note} (a human reopens, drops or closes) | proposals {limit?} |
                    dismiss {task_id, note} (cancel an INTERRUPTED task instead of resuming it) |
                    task_detail {task_id} | replay {since?, until?} | knowledge {query?, limit?} |
                    skills | presentation | benchmarks {limit?} | experiments {limit?} |
                    quality_run {only?, brain?} | quality_runs {limit?} | compare_brains {a, b, only?} |
                    codebench_run {brains?} | features | feature_promote {id} | startup {enabled?} | task_phases {task_id} | memories | memory_forget {id} |
                    memory_correct {id, text} (the human rewrites one remembered fact in place) | memory_export | voice_set {voice} |
                    presentation_feedback {presentation_id, action?} |
                    autonomy {enabled?} | cycle_now |
                    brains_get | brains_save {providers, order} |
                    brain_models {id, api_key?} | brain_test {id}
  server -> client: hello {name, tools, interrupted, running, queue, recent} | state | queue {items} |
                    user | think | tool_start | tool_result | ask | final |
                    task {event} | checkpoint | recovery {event} | verification |
                    history | task_events | verifications | self_model |
                    objectives | autonomy_status | autonomy {event} | objective {event} | cycle {event} |
                    task_detail | replay | knowledge | research {event} | knowledge {event} |
                    skills | skill {event} | presentation {event} | presentation_plan |
                    benchmarks | experiments | benchmark {event} | experiment {event} |
                    quality_runs | quality {event} | brief {event: checked|filed|refused, proof?, problems?, objective_id?} |
                    hunt {event: filed|refused, objective_id?, problems?} |
                    reflection {event} | memories {facts} | memory_exported {path, count} |
                    notice | error | pong | brain | brains | brain_models | brain_test

Sessions are observers: the task runs in ``syrax.core`` and continues when the
browser disconnects. Journaled events (think, tool_*, ask, answer, final, brain
failover/answered, task/checkpoint/recovery/verification) are written to the
durable journal first and fanned out to every connected session; ``state``,
``notice``, ``error``, panel replies and the ``user`` echo are direct.
"""

import asyncio
import dataclasses
import json
import os
import re
import time
from pathlib import Path
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import starlette.websockets
import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response

from app.logger import logger

from syrax import auth, browser, presence, redact, voice
from syrax import brains as brains_mod
from syrax.brains import PROVIDERS, get_router
from syrax.core import get_core
from syrax import permissions
from syrax import startup
from syrax.journal import JournalError, get_journal
from syrax.selfmodel import SECTIONS

redact.install()  # every log line of this process has credential-shaped strings masked (audit 2026-10-25)

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
# A page this server serves (the HUD at /hud) talks to it from the server's own origin.
ALLOWED_ORIGINS |= {f"http://{h}:{PORT}" for h in ("127.0.0.1", "localhost", HOST)}

# The desktop HUD (hud/): served by SYRAX itself so it runs on the core's origin; only these
# files, never the folder (node_modules and the Electron shell stay on disk).
HUD_DIR = Path(__file__).resolve().parents[2] / "hud"
HUD_FILES = {"hud.html": "text/html; charset=utf-8", "link.js": "text/javascript; charset=utf-8"}
# Public feeds the HUD draws that send no CORS headers (fine from file://, blocked from the core's origin):
# the core fetches them for the page, this allowlist only, cached a minute.
HUD_FEEDS = {
    "solar": "https://services.swpc.noaa.gov/products/solar-wind/plasma-1-day.json",
    "kp": "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json",
}
HUD_FEED_TTL_S = 60
_hud_feed_cache: dict = {}


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
    try:
        await core.settle_interrupted()  # the boot policy: what a restart cut is dismissed or kept for a human
    except Exception as e:
        logger.warning(f"boot policy for interrupted tasks failed: {e}")
    try:
        rq = await core.requeue_after_boot()  # human requests that waited across the restart
        if rq["dropped"] or rq["started"]:
            logger.warning(f"queued requests after restart: started {rq['started']}, cancelled as stale {rq['dropped']}")
    except Exception as e:
        logger.warning(f"queue after restart failed: {e}")
    from syrax import stallwatch

    # if the event loop ever blocks, the stacks of every thread are kept (live 2026-10-12: two silent stalls)
    watchdog = stallwatch.Watchdog(asyncio.get_running_loop(), journal).start()
    if core.autonomy.enabled:
        core.autonomy.start()
        logger.info("autonomy loop started")
    voice.load_voice(journal)  # the voice the human picked in the UI last time
    from syrax import reminders

    # reminders fire from SYRAX's own loop (journaled; the UI shows and speaks them)
    reminder_loop = asyncio.create_task(reminders.loop(journal, reminders.desktop_notify))
    from syrax import alerts

    alert_loop = asyncio.create_task(alerts.loop(journal))  # spoken warnings when the machine is in trouble
    from syrax import proactive

    checkin_loop = asyncio.create_task(proactive.loop(journal))  # speaks up when it has something useful
    logger.info(f"SYRAX online at ws://{HOST}:{PORT}/ws")
    # Warm the local ear in the background so the first voice command is fast.
    warm = asyncio.create_task(asyncio.to_thread(_warm_whisper))
    yield
    watchdog.stop()
    reminder_loop.cancel()
    alert_loop.cancel()
    checkin_loop.cancel()
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
    """A page SYRAX serves or expects (its Origin is allowed) may call; anything without an Origin
    needs the token (Phase 7: a local process is not a page)."""
    ok, why = auth.verdict(request.headers.get("origin"), ALLOWED_ORIGINS,
                           auth.presented(request.headers.raw, request.query_params.get(auth.QUERY)))
    if not ok:
        raise HTTPException(status_code=403, detail=why)


def _ws_allowed(ws: WebSocket) -> tuple:
    return auth.verdict(ws.headers.get("origin"), ALLOWED_ORIGINS, auth.presented(ws.headers.raw, ws.query_params.get(auth.QUERY)))


@app.get("/token")
async def token_for_page(request: Request):
    """The token, for a page the core serves (same-origin) so it can present it too; refused otherwise."""
    origin = request.headers.get("origin") or request.headers.get("referer", "")
    if not any(origin.startswith(o) for o in ALLOWED_ORIGINS if o):
        raise HTTPException(status_code=403, detail="only a page SYRAX serves may read the token")
    return {"token": auth.token()}


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


UPLOAD_MAX_BYTES = 50 * 1024 * 1024


def upload_dir() -> Path:
    from app.config import config

    return Path(config.workspace_root) / "uploads"


@app.post("/upload")
async def upload(request: Request, name: str = ""):
    """A file the human dropped on the UI, saved in the workspace for SYRAX to work on
    (feature catalog: file_processor). Same origin rule as the voice endpoints."""
    _check_origin(request)
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    if len(data) > UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"files up to {UPLOAD_MAX_BYTES // (1024 * 1024)} MB")
    safe = re.sub(r"[^\w.\- ]", "_", Path(str(name or "")).name).strip(" .")[:120] or "file"
    dest = upload_dir() / f"{time.strftime('%Y%m%d-%H%M%S')}-{safe}"
    await asyncio.to_thread(lambda: (dest.parent.mkdir(parents=True, exist_ok=True), dest.write_bytes(data)))
    await get_journal().record("file.uploaded", {"path": str(dest), "bytes": len(data), "name": safe})
    return {"path": str(dest), "bytes": len(data)}


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


@app.get("/hud")
async def hud_redirect():
    # the page lives at /hud/ so its relative `link.js` resolves beside it (live 2026-10-13: at /hud the
    # script loaded from /link.js, 404, and the HUD stayed black)
    return RedirectResponse("/hud/", status_code=308)


@app.get("/hud/")
async def hud_page():
    return await hud_file("hud.html")


@app.get("/hud/feed/{name}")
async def hud_feed(name: str):
    if name not in HUD_FEEDS:
        raise HTTPException(status_code=404, detail="no such feed")
    hit = _hud_feed_cache.get(name)
    if hit and time.time() - hit[0] < HUD_FEED_TTL_S:
        return Response(content=hit[1], media_type="application/json")
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.get(HUD_FEEDS[name])
            r.raise_for_status()
            body = r.content
    except Exception as e:
        logger.warning(f"HUD feed {name} failed: {e}")
        raise HTTPException(status_code=502, detail="feed unavailable")
    _hud_feed_cache[name] = (time.time(), body)
    return Response(content=body, media_type="application/json")


@app.get("/hud/{name}")
async def hud_file(name: str):
    if name not in HUD_FILES or not (HUD_DIR / name).is_file():
        raise HTTPException(status_code=404, detail="no such HUD file")
    return FileResponse(HUD_DIR / name, media_type=HUD_FILES[name], headers={"Cache-Control": "no-cache"})


@app.get("/voice")
async def voice_status(request: Request):
    _check_origin(request)  # which ear and voice this machine runs is internal state (audit 2026-10-25)
    return {
        "tts_voice": voice.TTS_VOICE,
        "stt": "groq" if get_router().store.key("groq") else f"whisper-{voice.local_whisper.size}",
        "whisper": voice.local_whisper.status,
    }


# /self: the story sections (who SYRAX is, how it did) stay readable like /health; the sections that describe this
# machine and this checkout (host, disk, paths, git state, the running task: summary, structure, runtime, all) need an
# allowed Origin or the token, as /stt does (audit 2026-10-25). The HUD and the UI never read /self; probe.py sends
# the UI's Origin; a local script passes ?token= or X-SYRAX-Token (`python syrax.py --token`).
SELF_OPEN_SECTIONS = {"identity", "behavior", "capabilities", "performance", "weaknesses", "proposals", "brains"}


@app.get("/self")
async def self_model(request: Request, section: str = "summary"):
    """Read-only self-model (evidence-based). ?section=summary|identity|structure|runtime|behavior|capabilities|weaknesses|all"""
    if section in SECTIONS and section not in SELF_OPEN_SECTIONS:
        _check_origin(request)
    try:
        return await asyncio.to_thread(get_core().selfmodel.snapshot, section)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/health")
async def health():
    router = get_router()
    return {"name": "SYRAX", "status": "online", "brain": router.active}


# Jobs that belong to the core, not to the browser tab that asked for them
# (quality runs, brain comparisons, a forced cycle). Closing a session must not
# kill them: the UI observes, the core keeps working.
DETACHED: set = set()


# A human objective needs a machine-verifiable check (owner's decision,
# 2026-10-10): task_success, which only asks whether the task said SUCCESS, is
# no longer accepted. Each kind names the field it needs.
OBJECTIVE_CHECKS = {
    "skill_verified": "name", "tool_verified": "tool", "knowledge_stored": "topic",
    "change_released": None, "file_present": "path", "file_absent": "path", "quality_case_passes": "case",
}


def objective_check_problem(check: Optional[dict]) -> Optional[str]:
    if not check:
        return "a check is required, one of " + ", ".join(OBJECTIVE_CHECKS)
    kind = check.get("kind")
    if kind not in OBJECTIVE_CHECKS:
        return "kind must be one of " + ", ".join(OBJECTIVE_CHECKS)
    field = OBJECTIVE_CHECKS[kind]
    if field and not str(check.get(field) or "").strip():
        return f"{kind} needs {field!r}"
    if kind in ("file_present", "file_absent"):
        from syrax.autonomy import check_path
        if check_path(check.get("path")) is None:
            return "path must be inside the repository (or backend/workspace)"
    if kind == "change_released" and "files" in check:
        files = check.get("files")
        if not isinstance(files, list) or not files or not all(isinstance(f, str) and f and not f.startswith(("/", "\\")) and ":" not in f
                                                                and ".." not in f.replace("\\", "/").split("/") for f in files):
            return "files must be a non-empty list of repository-relative paths"
    return None


class Session:
    """One WebSocket connection: observes the core, routes commands to it."""

    def __init__(self, ws: WebSocket, probe: bool = False):
        self.ws = ws
        self.probe = probe  # syrax.probe checking the service: the human's briefing is not for it
        self.id = uuid.uuid4().hex[:12]
        self.core = get_core()
        self.closed = False
        self._lock = asyncio.Lock()
        self.aux: set = set()

    def spawn(self, coro, detached: bool = False) -> None:
        """Run slow side jobs off the receive loop. Session jobs (model lists,
        brain tests) die with the session; detached jobs outlive it."""
        t = asyncio.create_task(coro)
        owner = DETACHED if detached else self.aux
        owner.add(t)
        t.add_done_callback(owner.discard)

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
                "tool_levels": permissions.levels_for(agent.available_tools.tool_map.keys()),
                "interrupted": snap["interrupted"],
                "running": snap["running"],
                "queue": snap["queue"],
                "recent": snap["recent"],
                "autonomy": await asyncio.to_thread(self.core.autonomy.status),
                "startup": startup.status(),
                "voice": {"current": voice.current_voice(get_journal()), "voices": voice.VOICES},
                "presentation": snap["presentation"],
                "presence": snap["presence"],
            }
        )
        await self.send({"type": "brains", **get_router().describe()})
        if not self.probe:
            await self._daily_briefing()
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
        elif kind == "task" and presence.parse_command(text):
            # "hide" / "show" / "go minimal": a visibility change, never a task, allowed while one runs
            await self.core.presence.set(presence.parse_command(text), by="voice" if msg.get("voice") else "text")
        elif kind == "presence":
            try:
                await self.core.presence.set(str(msg.get("visibility") or ""), by=str(msg.get("by") or "ui")[:20])
            except ValueError as e:
                await self.send({"type": "notice", "text": str(e)})
        elif kind == "task":
            if not text:
                return
            queue = bool(msg.get("queue"))
            if self.core.busy and not queue:
                await self.send(
                    {"type": "notice", "text": "Already executing. Stop it first."}
                )
                return
            await self.core.broadcast({"type": "user", "text": text, "voice": bool(msg.get("voice"))})
            request = text + VOICE_HINT if msg.get("voice") else text
            try:
                started = await self.core.submit(request, said=text, session_id=self.id, queue=queue)
            except RuntimeError as e:
                await self.send({"type": "error", "message": str(e)})
                return
            if started is None:  # another task started while this one waited
                await self.send({"type": "notice", "text": "Already executing. Stop it first."})
                return
            waiting = next((q for q in self.core.queued() if q["task_id"] == started), None)
            if waiting is not None:
                await self.send({"type": "notice", "text": f"Queued (position {waiting['position']}): it runs when the current task ends.",
                                 "action": {"label": "REMOVE", "msg": {"type": "queue_cancel", "task_id": started}}})
        elif kind == "queue":
            await self.send({"type": "queue", "items": self.core.queued()})
        elif kind == "queue_cancel":
            tid = str(msg.get("task_id") or "")
            note = str(msg.get("note") or "removed by human")[:200]
            if not await self.core.cancel_queued(tid, note=note):
                await self.send({"type": "notice", "text": "No such queued request."})
        elif kind == "answer":
            if not await self.core.answer(text, session_id=self.id):
                await self.send({"type": "notice", "text": "No pending question."})
        elif kind == "stop":
            # Live 2026-10-03: an autonomous release was "aborted by human" and
            # nothing said who sent the stop. Journal where it came from.
            running = self.core.current
            if running is not None and self.core.busy:
                await self.core.journal.record("task.stop_requested", {
                    "session": self.id, "origin": self.ws.headers.get("origin"),
                    "client": self.ws.headers.get("user-agent", "")[:120], "reason": str(msg.get("reason") or "")[:200],
                }, task_id=running.task_id)
            await self.core.cancel()
        elif kind == "reset":
            await self.core.reset()
            await self.send({"type": "notice", "text": "Memory wiped."})
        elif kind == "history":
            limit = _limit(msg.get("limit"), 20)
            tasks = await asyncio.to_thread(journal.tasks, limit)
            await self.send({"type": "history", "tasks": tasks})
        elif kind == "task_phases":
            from syrax import phases

            tid = str(msg.get("task_id") or "")
            events = await asyncio.to_thread(journal.events, tid, 5000)
            await self.send({"type": "task_phases", "task_id": tid, "phases": phases.path(events)})
        elif kind == "task_events":
            tid = str(msg.get("task_id") or "")
            events = await asyncio.to_thread(journal.events, tid)
            await self.send({"type": "task_events", "task_id": tid, "events": events})
        elif kind == "quality_run":
            if self.core.busy:
                await self.send({"type": "notice", "text": "Already executing. Stop it first."})
                return
            only = msg.get("only") if isinstance(msg.get("only"), list) else None
            self.spawn(self._quality(only, str(msg.get("brain") or "") or None), detached=True)
        elif kind == "compare_brains":
            if self.core.busy:
                await self.send({"type": "notice", "text": "Already executing. Stop it first."})
                return
            a, b = str(msg.get("a") or ""), str(msg.get("b") or "")
            only = msg.get("only") if isinstance(msg.get("only"), list) else None
            self.spawn(self._compare_brains(a, b, only), detached=True)
        elif kind == "memories":
            from syrax.memory import get_memory

            await self.send({"type": "memories", "facts": await asyncio.to_thread(get_memory().facts)})
        elif kind == "memory_forget":
            # the human removes one remembered fact from the memory panel (by its id)
            from syrax.memory import get_memory

            fid = str(msg.get("id") or "").strip()
            gone = await asyncio.to_thread(get_memory().forget, fid) if fid.isdigit() else []
            await self.send({"type": "notice", "text": f"Forgot: {gone[0]}" if gone else f"No remembered fact {fid!r}."})
            await self.send({"type": "memories", "facts": await asyncio.to_thread(get_memory().facts)})
        elif kind == "memory_correct":
            # the human rewrites one remembered fact in place (memory panel EDIT); the old text stays in the journal
            from syrax.memory import CorrectRefused, get_memory

            fid, text = str(msg.get("id") or "").strip(), str(msg.get("text") or "")
            try:
                fact = await asyncio.to_thread(get_memory().correct, fid, text)
            except CorrectRefused as e:
                await self.send({"type": "notice", "text": str(e)})
            else:
                await self.send({"type": "notice", "text": f"Corrected: {fact['text']}"})
            await self.send({"type": "memories", "facts": await asyncio.to_thread(get_memory().facts)})
        elif kind == "memory_export":
            # one JSON file with every fact (provenance included) and the conclusion/web knowledge, credential-masked
            from syrax.memory import get_memory

            try:
                out = await asyncio.to_thread(get_memory().export)
            except Exception as e:  # a full disk or a locked journal: say so, never pretend a file exists
                await self.send({"type": "notice", "text": f"Memory export failed: {e}"})
            else:
                await self.send({"type": "memory_exported", "path": out["path"], "count": out["count"]})
        elif kind == "voice_set":
            try:
                await asyncio.to_thread(voice.set_voice, journal, str(msg.get("voice") or ""))
            except ValueError as e:
                await self.send({"type": "notice", "text": str(e)})
                return
            await self.send({"type": "voice_status", "current": voice.current_voice(journal), "voices": voice.VOICES})
        elif kind == "startup":
            # the human's switch: does SYRAX start at the next login (never stops this run)
            if "enabled" in msg:
                try:
                    st = await asyncio.to_thread(startup.set_enabled, bool(msg.get("enabled")))
                except (RuntimeError, OSError) as e:
                    await self.send({"type": "notice", "text": f"start with Windows: {e}"})
                    return
                await journal.record("startup.toggled", {"enabled": st["enabled"], "how": st["how"]})
            await self.send({"type": "startup_status", **startup.status()})
        elif kind == "features":
            from syrax import catalog

            taken = {o.get("key"): o for o in await asyncio.to_thread(journal.objectives, 500)}
            rows = [{**dataclasses.asdict(f), "objective": (taken.get(catalog.objective_key(f)) or {}).get("id"),
                     "objective_status": (taken.get(catalog.objective_key(f)) or {}).get("status")} for f in catalog.CATALOG]
            await self.send({"type": "features", "features": rows, "counts": catalog.counts()})
        elif kind == "feature_promote":
            from syrax import catalog

            try:
                row = await journal.run(catalog.promote, journal, str(msg.get("id") or ""), "human")
            except (KeyError, ValueError) as e:
                await self.send({"type": "notice", "text": f"feature_promote: {e}"})
                return
            text = "already an objective" if row.get("duplicate") else f"objective #{row.get('id')} created"
            await self.send({"type": "notice", "text": f"feature {msg.get('id')}: {text}"})
        elif kind == "codebench_run":
            if self.core.busy:
                await self.send({"type": "notice", "text": "Already executing. Stop it first."})
                return
            brains = [str(b) for b in msg.get("brains")] if isinstance(msg.get("brains"), list) else None
            self.spawn(self._codebench(brains), detached=True)
        elif kind == "presentation_feedback":
            pid = str(msg.get("presentation_id") or "")
            if not await self.core.presentation.feedback(pid, str(msg.get("action") or "dismiss")):
                await self.send({"type": "notice", "text": "That element is no longer shown."})
        elif kind == "briefing":
            from syrax import briefing

            hours = max(1, min(int(msg.get("hours") or 24), 24 * 14))
            text = await asyncio.to_thread(briefing.compose, journal, time.time() - hours * 3600)
            await self.send({"type": "briefing", "text": text})
        elif kind == "proposals":
            await self.send({"type": "proposals", "proposals": await asyncio.to_thread(self.core.selfmodel.proposals, _limit(msg.get("limit"), 10))})
        elif kind == "quality_runs":
            await self.send({"type": "quality_runs", "runs": await asyncio.to_thread(journal.quality_runs, _limit(msg.get("limit"), 10))})
        elif kind == "benchmarks":
            await self.send({"type": "benchmarks", "benchmarks": await asyncio.to_thread(journal.benchmarks, _limit(msg.get("limit"), 20))})
        elif kind == "experiments":
            await self.send({"type": "experiments", "experiments": await asyncio.to_thread(journal.experiments, _limit(msg.get("limit"), 20))})
        elif kind == "presentation":
            await self.core.presentation.expire()
            await self.send({"type": "presentation_plan", **self.core.presentation.plan()})
        elif kind == "skills":
            await self.send({"type": "skills", "skills": await asyncio.to_thread(self.core.skills.list)})
        elif kind == "knowledge":
            query = str(msg.get("query") or "").strip()
            limit = _limit(msg.get("limit"), 50)
            rows = await asyncio.to_thread(
                (lambda: journal.knowledge_search(query, limit)) if query else (lambda: journal.knowledge_recent(limit))
            )
            await self.send({"type": "knowledge_list", "query": query, "knowledge": rows})
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
            check = msg.get("check") if isinstance(msg.get("check"), dict) else None
            problem = objective_check_problem(check)
            if problem:
                await self.send({"type": "notice", "text": f"objective_add check: {problem}"})
                return
            await journal.run(journal.add_objective_sync, goal, str(msg.get("reason") or "") or None, priority, "human", check)
        elif kind == "objective_update":
            # The human's override, e.g. reopening an objective that closed on
            # evidence SYRAX fabricated (2026-10-01). Always journaled with a note.
            status = str(msg.get("status") or "").upper()
            note = str(msg.get("note") or "").strip()
            try:
                oid = int(msg.get("id"))
            except (TypeError, ValueError):
                oid = 0
            if status not in ("OPEN", "DONE", "BLOCKED", "DROPPED") or not oid or not note:
                await self.send({"type": "notice", "text": "objective_update needs id, status (OPEN/DONE/BLOCKED/DROPPED) and a note."})
                return
            try:
                current = (await asyncio.to_thread(journal.objective, oid)) or {}
                if current.get("status") == "DONE" and status == "OPEN":
                    await journal.run(journal.reopen_objective_sync, oid, f"human: {note}")
                else:
                    await journal.update_objective(oid, status=status, note=f"human: {note}")
            except JournalError as e:
                await self.send({"type": "notice", "text": str(e)})
        elif kind == "hunt_add":
            from syrax import repro

            evidence = msg.get("evidence") if isinstance(msg.get("evidence"), list) else [msg.get("evidence")]
            tasks = msg.get("tasks") if isinstance(msg.get("tasks"), list) else []
            try:
                priority = int(msg.get("priority") or 1)
            except (TypeError, ValueError):
                priority = 1
            row, problems = await journal.run(repro.human_hunt, journal, str(msg.get("summary") or ""), evidence,
                                              str(msg.get("module") or "") or None, tasks, priority)
            if problems:
                await self.send({"type": "hunt", "event": "refused", "problems": problems})
            else:
                await self.send({"type": "hunt", "event": "filed", "objective_id": row["id"]})
        elif kind in ("brief_check", "brief_add"):
            if self.core.busy or getattr(getattr(self.core, "quality", None), "running", False):
                await self.send({"type": "notice", "text": "A brief is proved while SYRAX is idle: try again when the task ends."})
                return
            self.spawn(self._brief(msg, file=kind == "brief_add"), detached=True)
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
            self.spawn(self._cycle(), detached=True)
        elif kind == "dismiss":
            # An interrupted task whose in-flight operation is UNCERTAIN waits for
            # a person: resume it, or dismiss it here (journaled as cancelled).
            tid = str(msg.get("task_id") or "")
            note = str(msg.get("note") or "").strip()
            task = journal.task(tid) if tid else None
            if not task or task.get("status") != "INTERRUPTED" or not note:
                await self.send({"type": "notice", "text": "dismiss needs the task_id of an INTERRUPTED task and a note."})
                return
            await journal.record("task.cancelled", {"error": f"dismissed by human: {note}"}, task_id=tid)
            for o in await asyncio.to_thread(journal.objectives, 500, ["OPEN", "ACTIVE", "BLOCKED"]):
                if o.get("key") == f"uncertain-task:{tid}":
                    await journal.update_objective(o["id"], status="DROPPED", note=f"human dismissed task {tid}: {note}")
        elif kind == "resume":
            tid = str(msg.get("task_id") or "")
            try:
                # force + note: the human's word for a task whose last operation is UNCERTAIN (core.resume)
                problem = await self.core.resume(tid, session_id=self.id, force=bool(msg.get("force")),
                                                 note=str(msg.get("note") or "").strip())
            except JournalError as e:
                problem = str(e)
            if problem:
                await self.send({"type": "notice", "text": problem})
        elif kind == "brains_get":
            await self.send({"type": "brains", **get_router().describe()})
        elif kind == "brains_save":
            router = get_router()
            router.update(msg.get("providers") or {}, msg.get("order"),
                          self_change_brain=msg["self_change_brain"] if "self_change_brain" in msg else brains_mod._UNSET)
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

    async def _compare_brains(self, a: str, b: str, only) -> None:
        from syrax.experiments import render as render_exp

        try:
            row = await self.core.quality.compare_brains(a, b, only=only)
        except JournalError as e:
            await self.send({"type": "notice", "text": str(e)})
            return
        await self.core.broadcast({"type": "notice", "text": render_exp(row)})

    async def _codebench(self, brains) -> None:
        from syrax import codebench

        try:
            res = await codebench.run_all(self.core, brains=brains)
        except JournalError as e:
            await self.send({"type": "notice", "text": str(e)})
            return
        await self.core.broadcast({"type": "notice", "text": f"CODE BENCHMARK · {codebench.summary(res)}"})

    async def _brief(self, msg: dict, file: bool) -> None:
        """The human's brief, proved by repro.py: the test must fail on a clean tree of HEAD (and, with a fix diff,
        pass after it) before the change_released objective pinned to it is filed."""
        from syrax import repro
        from syrax.devloop import REPO_ROOT

        test_rel = str(msg.get("test_path") or "").strip()
        code = str(msg.get("test_code") or "")
        files = [str(f) for f in (msg.get("files") or []) if isinstance(f, str) and f.strip()]
        fix = str(msg.get("fix_diff") or "") or None
        goal = str(msg.get("goal") or "").strip()
        if file and (not goal or not files):
            await self.send({"type": "brief", "event": "refused", "problems": ["brief_add needs a goal and the files it changes"]})
            return
        try:
            base = await asyncio.to_thread(repro.resolve, REPO_ROOT, "HEAD")
            problems = await asyncio.to_thread(repro.screen, test_rel, code, files, REPO_ROOT, base)
            if fix:
                problems += await asyncio.to_thread(repro.phantom_paths, fix, REPO_ROOT, base)
            if problems:
                await self.send({"type": "brief", "event": "refused", "problems": problems})
                return
            await self.send({"type": "notice", "text": f"Proving {test_rel} on {base[:7]}..."})
            proof = await asyncio.to_thread(repro.prove, REPO_ROOT, test_rel, code, fix, base)
        except Exception as e:  # a proof that cannot run is not a verdict
            await self.send({"type": "brief", "event": "refused", "problems": [f"the proof could not run: {e}"]})
            return
        ok = proof.get("verdict") in (repro.ACCEPT_WITH_FIX if fix else repro.ACCEPT_WITHOUT_FIX)
        if not file or not ok:
            await self.send({"type": "brief", "event": "checked" if ok else "refused", "proof": repro.compact(proof)})
            return
        try:
            priority = max(1, min(int(msg.get("priority") or 1), 9))
        except (TypeError, ValueError):
            priority = 1
        journal = self.core.journal
        row = await journal.run(repro.file_brief, journal, goal, str(msg.get("reason") or "") or None, test_rel, code, files,
                                proof, priority)
        if row is None:
            await self.send({"type": "brief", "event": "refused", "proof": repro.compact(proof),
                             "problems": ["this test was filed before (same sha256)"]})
            return
        await self.send({"type": "brief", "event": "filed", "objective_id": row["id"], "proof": repro.compact(proof)})

    async def _quality(self, only, brain=None) -> None:
        from syrax.quality import format_report

        try:
            row = await self.core.quality.run(only=only, brain=brain)
        except JournalError as e:
            await self.send({"type": "notice", "text": str(e)})
            return
        await self.core.broadcast({"type": "notice", "text": format_report(row)})

    async def _daily_briefing(self) -> None:
        """Once a day, the first session that opens gets what SYRAX did,
        learned and proposes, composed from the journal (no model call)."""
        from syrax import briefing

        journal = self.core.journal
        try:
            if not await asyncio.to_thread(briefing.due, journal):
                return
            last = float(journal.get_meta(briefing.META_KEY) or 0) or None
            text = await asyncio.to_thread(briefing.compose, journal, last)
            await asyncio.to_thread(briefing.mark_shown, journal)
        except Exception as e:  # a briefing must never break a session
            logger.warning(f"daily briefing failed: {e}")
            return
        await self.send({"type": "briefing", "text": text})
        try:
            await self.core.presentation.show("card", "daily briefing", {"title": "Daily briefing", "text": text},
                                              attention="focus", ttl_s=900, slot="briefing")
        except Exception as e:
            logger.warning(f"briefing card failed: {e}")

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


# Live 2026-10-22 18:07: a client connected while the core was still building its agent (~14 s after a start) and
# left before boot ended; Session.send swallowed the failed sends, the loop then read the socket, and starlette 1.x
# raised WebSocketDisconnected, a RuntimeError and not a WebSocketDisconnect: a full "SYRAX session error"
# traceback in the human's console for a client that had simply gone.
CLIENT_GONE = tuple(c for c in (WebSocketDisconnect, getattr(starlette.websockets, "WebSocketDisconnected", None)) if c)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    ok, why = _ws_allowed(ws)
    if not ok:
        logger.warning(f"Rejected WebSocket: {why}")
        await ws.close(code=1008)
        return

    await ws.accept()
    session = Session(ws, probe=ws.query_params.get("probe") == "1")
    try:
        await session.boot()
        while not session.closed:  # a send that failed means the client is gone
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
    except CLIENT_GONE:
        pass
    except Exception as e:
        logger.exception("SYRAX session error")
        await session.send({"type": "error", "message": _explain(e)})
    finally:
        await session.close()


@app.websocket("/live")
async def live_endpoint(ws: WebSocket):
    """Live talk (syrax/live.py): the microphone to Gemini Live and its voice back. Same rule as /ws."""
    ok, why = _ws_allowed(ws)
    if not ok:
        logger.warning(f"Rejected live WebSocket: {why}")
        await ws.close(code=1008)
        return
    await ws.accept()
    from syrax import brains, live

    await live.serve(ws, get_core(), brains.get_router().store.key("gemini"))


def main() -> None:
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
