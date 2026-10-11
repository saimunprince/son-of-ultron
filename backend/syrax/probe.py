"""Live probes of the running SYRAX, for the capability matrix (M3).

What a person checks by hand, done by machine against the running service:
the launcher's process is alive, /health answers, the UI serves its page, a
WebSocket session gets its hello, the self-model reads without mojibake, and
one harmless voice round trip (speak a sentence, transcribe it back). The
result is the evidence dict that capmatrix.live_checks reads. Read-only: no
task, no command. The WebSocket session says it is a probe (?probe=1), so it
never takes the human's daily briefing.

This file produces evidence about SYRAX, so its own releases may not change it (devloop.JUDGES).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from syrax.journal import BACKEND_ROOT

REPO_ROOT = BACKEND_ROOT.parent
PID_FILE = REPO_ROOT / "syrax.pid"
SENTENCE = "SYRAX, open the journal."
HEARD = ("syrax", "journal", "open")


def endpoints() -> Dict[str, str]:
    """Where the running service listens, from the same settings it was started with."""
    port = int(os.getenv("SYRAX_PORT", "8765"))
    ui_port = int(os.getenv("SYRAX_UI_PORT", "3000"))
    origins = [o.strip() for o in os.getenv("SYRAX_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if o.strip()]
    return {"http": f"http://127.0.0.1:{port}", "ws": f"ws://127.0.0.1:{port}/ws?probe=1",
            "ui": f"http://localhost:{ui_port}", "origin": origins[0]}


def http(url: str, origin: str, data: Optional[bytes] = None, headers: Optional[dict] = None,
         timeout: float = 60.0, raw: bool = False) -> dict:
    req = urllib.request.Request(url, data=data, headers={"Origin": origin, **(headers or {})})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            out: Dict[str, Any] = {"status": r.status, "ms": int((time.time() - t0) * 1000)}
            if raw:
                return {**out, "bytes": len(body), "_body": body}
            text = body.decode("utf-8", "replace")
            try:
                return {**out, "json": json.loads(text)}
            except ValueError:
                return {**out, "text": text[:2000]}
    except Exception as e:
        return {"error": str(e)[:300], "ms": int((time.time() - t0) * 1000)}


def pid_alive(pid: int) -> bool:
    try:
        import psutil

        return psutil.pid_exists(pid)
    except ImportError:
        pass
    if sys.platform == "win32":  # os.kill(pid, 0) would terminate the process on Windows
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def process(pid_file: Path = PID_FILE) -> dict:
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return {}
    return {"pid": pid, "pid_alive": pid_alive(pid)}


def ws_hello(url: str, origin: str, timeout: float = 30.0) -> dict:
    try:
        from websockets.sync.client import connect

        deadline = time.time() + timeout
        with connect(url, origin=origin, open_timeout=timeout, max_size=None) as ws:
            while time.time() < deadline:
                e = json.loads(ws.recv(timeout=max(0.1, deadline - time.time())))
                if e.get("type") == "hello":
                    return {"hello": {"tools": sorted(e.get("tools") or []), "running": bool(e.get("running"))}}
        return {"error": "no hello"}
    except Exception as e:
        return {"error": str(e)[:300]}


def voice_roundtrip(base: str, origin: str) -> dict:
    out: Dict[str, Any] = {}
    tts = http(f"{base}/tts", origin, data=json.dumps({"text": SENTENCE}).encode(),
               headers={"Content-Type": "application/json"}, timeout=90, raw=True)
    audio = tts.pop("_body", b"")
    out["tts"] = tts
    if audio:
        stt = http(f"{base}/stt", origin, data=audio, headers={"Content-Type": "audio/mpeg"}, timeout=180)
        out["stt"] = stt
        heard = str((stt.get("json") or {}).get("text", "")).lower()
        out["roundtrip_pass"] = any(w in heard for w in HEARD)
    return out


def collect(eps: Optional[Dict[str, str]] = None, voice: bool = True, pid_file: Path = PID_FILE) -> Dict[str, Any]:
    """Every probe; a probe that cannot run says why instead of passing."""
    eps = eps or endpoints()
    origin = eps["origin"]
    ev: Dict[str, Any] = {"generated": time.strftime("%Y-%m-%d %H:%M:%S %z"), "endpoints": eps, "process": process(pid_file)}
    ev["http"] = {"health": http(f"{eps['http']}/health", origin, timeout=15)}
    st = http(f"{eps['http']}/self?section=structure", origin)
    text = json.dumps(st.get("json", st), ensure_ascii=False)
    ev["http"]["self_structure"] = {"status": st.get("status", st.get("error")),
                                    "mojibake_count": text.count("â†") + text.count("Ã") if st.get("json") is not None else None}
    ui = http(eps["ui"], origin, timeout=30)
    m = re.search(r"<title>(.*?)</title>", ui.get("text", "") or "")
    ev["ui"] = {"status": ui.get("status", ui.get("error")), "title": m.group(1) if m else None}
    ev["ws"] = ws_hello(eps["ws"], origin)
    if voice:
        ev["voice"] = voice_roundtrip(eps["http"], origin)
    return ev
