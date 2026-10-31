"""phone: see what SYRAX is doing from a phone on the same WiFi, and stop it. Nothing else.

From the Ultron comparison of 2026-10-31 (its phone dashboard). The owner's choice of scope: the phone may read and may
press the emergency stop; it can never send a request, clear the stop, or change a setting. So a stolen phone link can
at most stop SYRAX, which is the safe direction.

- Off until the owner turns it on: `python syrax.py --phone on` (backend/config/phone.json; only a human writes config).
- A separate small server on the LAN address (PORT, default 8770); the core itself stays on 127.0.0.1.
- Its own token (backend/config/phone.token, owner-readable only), never the core's ws.token. The link carries it after
  `#`, so it is not sent in requests, logs or Referer; the page sends it as X-SYRAX-Token.
- Plain HTTP on the home network: someone who can read the WiFi traffic can read the status and could stop SYRAX."""

from __future__ import annotations

import contextlib
import hmac
import json
import socket
import time
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import Request

from syrax import auth
from syrax.journal import BACKEND_ROOT

SETTINGS = BACKEND_ROOT / "config" / "phone.json"
TOKEN_FILE = BACKEND_ROOT / "config" / "phone.token"
PORT = 8770


def settings(path: Optional[Path] = None) -> dict:
    try:
        data = json.loads(Path(path or SETTINGS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"enabled": False, "port": PORT}
    return {"enabled": data.get("enabled") is True, "port": int(data.get("port") or PORT)}


def save(enabled: bool, path: Optional[Path] = None, port: int = PORT) -> dict:
    p = Path(path or SETTINGS)
    p.write_text(json.dumps({"enabled": bool(enabled), "port": int(port)}), encoding="utf-8")
    return settings(p)


def lan_ip() -> str:
    """This PC's address on the home network (no packet is sent: a UDP connect only picks the route)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def link(host: Optional[str] = None, port: Optional[int] = None, token_path: Path = TOKEN_FILE) -> str:
    return f"http://{host or lan_ip()}:{port or settings()['port']}/#t={auth.token(token_path)}"


def _ok(given: Optional[str], token_path: Path) -> bool:
    return bool(given) and hmac.compare_digest(str(given), auth.token(token_path))


def status_of(core: Any) -> dict:
    """What the phone shows: the stop, the autonomy, what runs now, and the last tasks (goal cut to 120 characters)."""
    a = core.autonomy.status()
    running = core.current if core.busy else None
    tasks = [{"goal": str(t.get("goal") or "")[:120], "status": t.get("status"), "kind": t.get("kind"), "at": t.get("updated")}
             for t in core.journal.tasks(limit=6)]
    return {"at": time.time(), "estop": a.get("estop"), "autonomy": {k: a.get(k) for k in ("enabled", "level", "state", "autonomous_today", "daily_tasks")},
            "running": {"goal": running.goal[:120], "kind": running.kind} if running else None, "tasks": tasks}


def build_app(core_getter: Callable[[], Any], stop: Callable[..., Any], token_path: Path = TOKEN_FILE):
    """The phone's server: GET / (the page, no data in it), GET /status and POST /estop (both need the token)."""
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse

    app = FastAPI(title="SYRAX phone", docs_url=None, redoc_url=None, openapi_url=None)

    def check(request: Request) -> None:
        if not _ok(request.headers.get(auth.HEADER), token_path):
            raise HTTPException(status_code=401, detail="token required")

    @app.get("/", response_class=HTMLResponse)
    async def page():
        return PAGE

    @app.get("/status")
    async def status(request: Request):
        check(request)
        import asyncio

        return await asyncio.to_thread(status_of, core_getter())

    @app.post("/estop")
    async def estop(request: Request):
        check(request)
        await stop(core_getter(), note="pressed on the phone page", who=f"phone {request.client.host if request.client else '?'}")
        return {"stopped": True}

    return app


class _Server:
    """uvicorn's Server without its signal capture: the core's own server owns Ctrl+C and SIGTERM."""

    def __new__(cls, config):
        import uvicorn

        class Quiet(uvicorn.Server):
            @contextlib.contextmanager
            def capture_signals(self):
                yield

        return Quiet(config)


def server(core_getter: Callable[[], Any], stop: Callable[..., Any], host: Optional[str] = None):
    """The phone server, ready to `await .serve()`, or None while the owner has not turned it on."""
    s = settings()
    if not s["enabled"]:
        return None
    import uvicorn

    auth.token(TOKEN_FILE)  # created (owner-only) before the first phone asks
    return _Server(uvicorn.Config(build_app(core_getter, stop), host=host or lan_ip(), port=s["port"], log_level="warning"))


PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SYRAX</title><style>
:root{--bg:#0d1117;--fg:#e6edf3;--mute:#8b949e;--card:#161b22;--line:#30363d;--red:#da3633}
@media (prefers-color-scheme: light){:root{--bg:#f6f8fa;--fg:#1f2328;--mute:#59636e;--card:#fff;--line:#d1d9e0}}
body{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:16px/1.45 system-ui,sans-serif}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:0 0 12px}
h1{font-size:20px;margin:0 0 12px}.mute{color:var(--mute);font-size:14px}ul{padding-left:18px;margin:6px 0}
button{width:100%;padding:18px;font-size:20px;font-weight:700;color:#fff;background:var(--red);border:0;border-radius:10px}
button:disabled{opacity:.5}</style></head><body>
<h1>SYRAX</h1><div id="s" class="card">Loading…</div>
<button id="b" onclick="stopIt()">EMERGENCY STOP</button>
<p class="mute">This page can only watch and stop. Clearing the stop is done on the computer.</p>
<script>
const t=new URLSearchParams(location.hash.slice(1)).get('t')||'';
const h={'X-SYRAX-Token':t};const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function load(){try{const r=await fetch('/status',{headers:h});if(!r.ok){s.textContent=r.status==401?'The link has no valid token.':'Error '+r.status;return}
const d=await r.json();const a=d.autonomy||{};
s.innerHTML=(d.estop?'<b>Emergency stop is ON</b><br>':'')+'Autonomy: '+esc(a.enabled?('level '+a.level+', '+((a.state||{}).state||'?')):'off')
+' · today '+esc(a.autonomous_today)+'/'+esc(a.daily_tasks)+'<br>Now: '+(d.running?esc(d.running.goal):'<span class="mute">idle</span>')
+'<ul>'+d.tasks.map(x=>'<li>'+esc(x.status)+' — '+esc(x.goal)+'</li>').join('')+'</ul>';b.disabled=!!d.estop}catch(e){s.textContent='SYRAX is not answering.'}}
async function stopIt(){if(!confirm('Stop SYRAX now?'))return;await fetch('/estop',{method:'POST',headers:h});load()}
load();setInterval(load,5000);
</script></body></html>"""
