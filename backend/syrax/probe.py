"""Live probes of the running SYRAX, for the capability matrix (M3).

What a person checks by hand, done by machine against the running service:
the launcher's process is alive, /health answers, the UI serves its page, a
WebSocket session gets its hello, the self-model reads without mojibake, and
one harmless voice round trip (speak a sentence, transcribe it back). Since
2026-10-26 the WebSocket session also asks for the queue (hello.queue is a
list and {"type": "queue"} answers with items), asks for a memory export
(memory_exported names a file that exists; the probe deletes the file it
asked for, so nothing is left behind) and, on the same machine, checks that
the newest backup snapshot verifies and is younger than BACKUP_MAX_AGE_H.
The result is the evidence dict that capmatrix.live_checks reads. Read-only
otherwise: no task, no command. The WebSocket session says it is a probe
(?probe=1), so it never takes the human's daily briefing. The probes
authenticate as the UI does: the first allowed Origin (SYRAX_ALLOWED_ORIGINS).

    python -m syrax.probe [--no-voice] [--backups-root DIR] [--pid-file FILE]

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
BACKUP_MAX_AGE_H = 48.0  # the idle cycle snapshots once a day; twice that and the backups have stopped
EXPORT_WAIT_S = 30.0


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


def queue_shape(hello: Optional[dict], answer: Optional[dict]) -> dict:
    """The pure part of the queue probe: hello carries a queue list and the queue message answered with
    an items list. {"hello_list", "answered", "items"}; the caller decides pass or fail."""
    h = hello or {}
    a = answer or {}
    hello_list = isinstance(h.get("queue"), list)
    answered = a.get("type") == "queue" and isinstance(a.get("items"), list)
    return {"hello_list": hello_list, "answered": answered, "items": len(a.get("items") or []) if answered else None}


def ws_session(url: str, origin: str, timeout: float = 30.0, export: bool = True) -> dict:
    """One probe session: the hello (tools, running, the queue), {"type": "queue"} answered, and, when
    `export` is on, {"type": "memory_export"} answered by memory_exported naming a file that exists;
    that file is deleted here. {"hello": {...}, "queue": {...}, "memory_export": {...}} or {"error"}."""
    try:
        from websockets.sync.client import connect

        deadline = time.time() + timeout
        out: Dict[str, Any] = {}
        hello: Optional[dict] = None
        with connect(url, origin=origin, open_timeout=timeout, max_size=None) as ws:
            while time.time() < deadline and hello is None:
                e = json.loads(ws.recv(timeout=max(0.1, deadline - time.time())))
                if e.get("type") == "hello":
                    hello = e
                    out["hello"] = {"tools": sorted(e.get("tools") or []), "running": bool(e.get("running")),
                                    "queue": e.get("queue") if isinstance(e.get("queue"), list) else None}
            if hello is None:
                return {"error": "no hello"}
            ws.send(json.dumps({"type": "queue"}))
            answer = None
            while time.time() < deadline and answer is None:
                e = json.loads(ws.recv(timeout=max(0.1, deadline - time.time())))
                if e.get("type") == "queue":
                    answer = e
            out["queue"] = queue_shape(hello, answer)
            if answer is None:
                out["queue"]["error"] = f"no queue answer within {timeout:g} s"
            if export:
                out["memory_export"] = _memory_export(ws, time.time() + EXPORT_WAIT_S)
        return out
    except Exception as e:
        return {"error": str(e)[:300]}


def _memory_export(ws, deadline: float) -> dict:
    """Ask for a memory export and clean it up: pass only when the named file existed; deleted afterwards."""
    ws.send(json.dumps({"type": "memory_export"}))
    while time.time() < deadline:
        e = json.loads(ws.recv(timeout=max(0.1, deadline - time.time())))
        if e.get("type") == "memory_exported":
            p = Path(str(e.get("path") or ""))
            existed = bool(e.get("path")) and p.is_file()
            deleted = False
            if existed:
                try:
                    p.unlink()
                    deleted = True
                except OSError as err:
                    return {"path": str(p), "count": e.get("count"), "existed": True, "deleted": False, "error": str(err)[:200]}
            return {"path": str(p), "count": e.get("count"), "existed": existed, "deleted": deleted}
        if e.get("type") == "notice" and "export failed" in str(e.get("text", "")).lower():
            return {"error": str(e.get("text"))[:300]}
    return {"error": f"no memory_exported within {EXPORT_WAIT_S:g} s"}


def backups_check(root: Optional[Path] = None, now: Optional[float] = None, max_age_h: float = BACKUP_MAX_AGE_H) -> dict:
    """The newest snapshot under root (backend/config/backups beside the running journal), verified against its
    manifest (syrax.backup.verify: sizes, sha256, integrity_check, row counts) and dated. {} when there is none;
    otherwise {"dir", "created", "age_h", "ok", "fresh", "problems"}: the live check passes only when ok and fresh."""
    from syrax import backup

    snaps = backup.snapshots(root or backup.BACKUP_ROOT)
    if not snaps:
        return {}
    newest = snaps[-1]
    v = backup.verify(newest)
    created = v.get("created")
    age_h = round(((now or time.time()) - float(created)) / 3600, 1) if isinstance(created, (int, float)) else None
    fresh = age_h is not None and 0 <= age_h <= max_age_h
    return {"dir": str(newest), "created": created, "age_h": age_h, "ok": bool(v.get("ok")), "fresh": fresh,
            "problems": list(v.get("problems") or []), "journal": v.get("journal"), "snapshots": len(snaps)}


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


def collect(eps: Optional[Dict[str, str]] = None, voice: bool = True, pid_file: Path = PID_FILE,
            backups_root: Optional[Path] = None) -> Dict[str, Any]:
    """Every probe; a probe that cannot run says why instead of passing."""
    eps = eps or endpoints()
    origin = eps["origin"]
    ev: Dict[str, Any] = {"generated": time.strftime("%Y-%m-%d %H:%M:%S %z"), "endpoints": eps, "process": process(pid_file)}
    try:
        ev["backups"] = backups_check(backups_root)
    except Exception as e:  # a folder that cannot be read is said, never skipped silently
        ev["backups"] = {"error": str(e)[:300]}
    ev["http"] = {"health": http(f"{eps['http']}/health", origin, timeout=15)}
    st = http(f"{eps['http']}/self?section=structure", origin)
    text = json.dumps(st.get("json", st), ensure_ascii=False)
    ev["http"]["self_structure"] = {"status": st.get("status", st.get("error")),
                                    "mojibake_count": text.count("â†") + text.count("Ã") if st.get("json") is not None else None}
    ui = http(eps["ui"], origin, timeout=30)
    m = re.search(r"<title>(.*?)</title>", ui.get("text", "") or "")
    ev["ui"] = {"status": ui.get("status", ui.get("error")), "title": m.group(1) if m else None}
    ev["ws"] = ws_session(eps["ws"], origin)
    if voice:
        ev["voice"] = voice_roundtrip(eps["http"], origin)
    return ev


def main(argv: Optional[list] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m syrax.probe", description="Live probes of the running SYRAX; prints the evidence JSON.")
    ap.add_argument("--no-voice", action="store_true", help="skip the TTS->STT round trip")
    ap.add_argument("--backups-root", help="the backups folder to check (default: backend/config/backups of this checkout)")
    ap.add_argument("--pid-file", help="the launcher's pid file (default: syrax.pid of this checkout)")
    a = ap.parse_args(argv)
    ev = collect(voice=not a.no_voice, pid_file=Path(a.pid_file) if a.pid_file else PID_FILE,
                 backups_root=Path(a.backups_root) if a.backups_root else None)
    print(json.dumps(ev, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
