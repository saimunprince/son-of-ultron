"""Phase 7 of the self-improvement plan: who may talk to the core.

A browser page sends an Origin header, and the allowed origins (the UI, the
HUD the core serves itself) are trusted as they were. A connection with no
Origin, or from anywhere else, is not a page SYRAX serves: it needs the
token. The token lives in backend/config/ws.token (created on first use,
owner-readable only, never committed); `python syrax.py --token` prints it,
and a page served by the core can read it from GET /token to send it as
well. It travels as `?token=` on a websocket URL or `X-SYRAX-Token` on an
HTTP request.
"""

from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path
from typing import Iterable, Optional

from syrax.journal import BACKEND_ROOT

TOKEN_FILE = Path(os.getenv("SYRAX_TOKEN_FILE", str(BACKEND_ROOT / "config" / "ws.token")))
HEADER = "x-syrax-token"
QUERY = "token"


def token(path: Path = TOKEN_FILE) -> str:
    """The token, created on first use (32 random bytes, url-safe)."""
    try:
        t = path.read_text(encoding="utf-8").strip()
        if t:
            return t
    except OSError:
        pass
    t = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(t + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)
    return t


def presented(headers: Iterable[tuple], query: Optional[str]) -> Optional[str]:
    """The token a request presents: the query parameter, else the header."""
    if query:
        return query.strip()
    for k, v in headers:
        name = k.decode() if isinstance(k, bytes) else str(k)
        if name.lower() == HEADER:
            return (v.decode() if isinstance(v, bytes) else str(v)).strip()
    return None


def verdict(origin: Optional[str], allowed: Iterable[str], given: Optional[str], expected: Optional[str] = None) -> tuple:
    """(ok, reason). An allowed Origin is a page SYRAX serves or expects: trusted. A foreign Origin is
    refused whatever it presents. No Origin needs the token."""
    if origin:
        return (True, "origin") if origin in set(allowed) else (False, f"origin {origin} not allowed")
    expected = expected if expected is not None else token()
    if given and hmac.compare_digest(given, expected):
        return True, "token"
    return False, "no origin and no valid token"
