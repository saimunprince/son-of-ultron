"""Phase 7 of the self-improvement plan: who may talk to the core. A page with an
allowed Origin is trusted as before; a foreign Origin is refused whatever it
presents; a connection with no Origin (a local process, curl) needs the token
on /ws, /live and the writing HTTP endpoints. The token is a local file,
never committed; the launcher prints it; a served page may read it."""

import os
import stat
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from syrax import auth, server
from syrax.devloop import JUDGES
from syrax.test_bridge import ORIGIN, boot, script  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]


def test_the_token_is_created_once_owner_only_and_never_committed(tmp_path):
    f = tmp_path / "ws.token"
    t = auth.token(f)
    assert len(t) >= 40 and auth.token(f) == t and not (tmp_path / "ws.tmp").exists()
    if os.name != "nt":
        assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert "backend/config/ws.token" in (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "backend/syrax/auth.py" in JUDGES


def test_the_verdict_trusts_an_allowed_origin_refuses_a_foreign_one_and_wants_the_token_otherwise():
    allowed = {"http://localhost:3000"}
    assert auth.verdict("http://localhost:3000", allowed, None, "T") == (True, "origin")
    assert auth.verdict("http://evil.example", allowed, "T", "T")[0] is False
    assert auth.verdict(None, allowed, "T", "T") == (True, "token")
    assert auth.verdict(None, allowed, "wrong", "T")[0] is False
    assert auth.verdict(None, allowed, None, "T") == (False, "no origin and no valid token")
    assert auth.presented([(b"x-syrax-token", b"abc")], None) == "abc" and auth.presented([], "q") == "q" and auth.presented([], None) is None


def test_ws_and_live_without_origin_need_the_token(script, tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "TOKEN_FILE", tmp_path / "ws.token")
    monkeypatch.setattr(auth, "token", lambda path=None: "SECRET")
    c = TestClient(server.app)
    with pytest.raises(WebSocketDisconnect) as e:
        with c.websocket_connect("/ws") as ws:
            ws.receive_json()
    assert e.value.code == 1008
    with c.websocket_connect("/ws?token=SECRET") as ws:
        boot(ws)  # the token in the query: a full boot, like the UI's
    with c.websocket_connect("/ws", headers={"x-syrax-token": "SECRET"}) as ws:
        boot(ws)
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect("/ws?token=SECRET", headers={"origin": "http://evil.example"}) as ws:
            ws.receive_json()  # a foreign page never gets in, token or not
    with c.websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)  # the UI's origin, as before
    with pytest.raises(WebSocketDisconnect) as e2:
        with c.websocket_connect("/live") as ws:
            ws.receive_json()
    assert e2.value.code == 1008


def test_writing_http_endpoints_without_origin_need_the_token_and_a_served_page_may_read_it(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "token", lambda path=None: "SECRET")
    c = TestClient(server.app)
    assert c.post("/upload?name=a.txt", content=b"12").status_code == 403
    assert c.post("/upload?name=a.txt", content=b"12", headers={"x-syrax-token": "SECRET"}).status_code != 403
    assert c.post("/upload?name=a.txt", content=b"12", headers=ORIGIN).status_code != 403
    assert c.get("/health").status_code == 200  # read-only stays open to the local machine
    assert c.get("/token").status_code == 403
    assert c.get("/token", headers=ORIGIN).json() == {"token": "SECRET"}
    assert c.get("/token", headers={"origin": "http://evil.example"}).status_code == 403


def test_the_launcher_prints_the_token(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("syrax_launcher_token", ROOT / "syrax.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(auth, "TOKEN_FILE", tmp_path / "ws.token")
    monkeypatch.setattr(auth, "token", lambda path=None: "PRINTED")
    out = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: out.append(" ".join(str(x) for x in a)))
    assert mod.main(["--token"]) == 0 and out == ["PRINTED"]
