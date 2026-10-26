"""Audit 2026-10-25 ("/token trusts the Referer"): GET /token handed the token to any request whose Origin OR
Referer began with an allowed origin. A Referer is a header any local process can write, and it is not an Origin.
The UI (localhost:3000) and the HUD (served by the core at /hud) send an Origin on every websocket and
cross-origin call and never read /token themselves. Only the Origin names a page now. A request with no Origin
may be a same-origin GET from a page the core serves itself (a browser omits the Origin on some same-origin
GETs): then, and only then, the Referer counts, and only when its origin is the core's own, never another allowed
origin (auth.page_may_read_token)."""

from syrax import auth, server
from syrax.test_bridge import ORIGIN, TestClient

CORE = f"http://127.0.0.1:{server.PORT}"
REFUSED = "only a page SYRAX serves may read the token"


def client(monkeypatch) -> TestClient:
    monkeypatch.setattr(auth, "token", lambda path=None: "SECRET")
    return TestClient(server.app)


def test_an_allowed_origin_reads_the_token(monkeypatch):
    c = client(monkeypatch)
    assert c.get("/token", headers=ORIGIN).json() == {"token": "SECRET"}  # the UI
    assert c.get("/token", headers={"origin": CORE}).json() == {"token": "SECRET"}  # the HUD, served by the core
    assert c.get("/token", headers={"origin": f"http://localhost:{server.PORT}"}).json() == {"token": "SECRET"}


def test_a_referer_from_an_allowed_origin_that_is_not_the_core_is_not_an_origin(monkeypatch):
    c = client(monkeypatch)
    for ref in ("http://localhost:3000/", "http://localhost:3000", "http://127.0.0.1:3000/replay?task=1"):
        r = c.get("/token", headers={"referer": ref})
        assert r.status_code == 403 and r.json()["detail"] == REFUSED, ref


def test_a_same_origin_referer_from_the_core_itself_reads_the_token(monkeypatch):
    c = client(monkeypatch)
    assert c.get("/token", headers={"referer": f"{CORE}/hud/"}).json() == {"token": "SECRET"}
    assert c.get("/token", headers={"referer": f"http://localhost:{server.PORT}/hud/hud.html?syrax=1#top"}).json() == {"token": "SECRET"}
    assert c.get("/token", headers={"referer": f"{CORE}"}).json() == {"token": "SECRET"}


def test_no_headers_and_lookalikes_are_refused(monkeypatch):
    c = client(monkeypatch)
    assert c.get("/token").status_code == 403
    assert c.get("/token", headers={"origin": "http://evil.example"}).status_code == 403
    assert c.get("/token", headers={"origin": "http://localhost:30000"}).status_code == 403  # a prefix is not the origin
    assert c.get("/token", headers={"origin": "null"}).status_code == 403  # an opaque origin (file://) is no page of ours
    assert c.get("/token", headers={"origin": "http://evil.example", "referer": f"{CORE}/hud/"}).status_code == 403  # a foreign Origin, whatever the Referer
    assert c.get("/token", headers={"referer": f"{CORE}.evil.example/hud/"}).status_code == 403
    assert c.get("/token", headers={"referer": f"http://evil.example/?next={CORE}/hud/"}).status_code == 403
    assert c.get("/token", headers={"referer": f"https://127.0.0.1:{server.PORT}/hud/"}).status_code == 403  # the scheme is part of the origin
    assert c.get("/token", headers={"referer": "not a url"}).status_code == 403
    assert c.get("/token", headers={"referer": ""}).status_code == 403


def test_the_rule_itself():
    allowed = {"http://localhost:3000", "http://127.0.0.1:3000", CORE}
    core = {CORE}
    assert auth.page_may_read_token("http://localhost:3000", None, allowed, core) == (True, "origin")
    assert auth.page_may_read_token(CORE, None, allowed, core) == (True, "origin")
    assert auth.page_may_read_token("http://evil.example", None, allowed, core) == (False, "origin http://evil.example not allowed")
    assert auth.page_may_read_token("http://evil.example", f"{CORE}/hud/", allowed, core)[0] is False
    assert auth.page_may_read_token(None, f"{CORE}/hud/", allowed, core) == (True, "referer same-origin with the core")
    assert auth.page_may_read_token(None, "http://localhost:3000/", allowed, core) == (False, REFUSED)
    assert auth.page_may_read_token(None, None, allowed, core) == (False, REFUSED)
    assert auth.page_origin(f"{CORE}/hud/?a=1#x") == CORE
    assert auth.page_origin(f"HTTP://127.0.0.1:{server.PORT}/hud/") == CORE  # scheme and host are case-insensitive
    assert auth.page_origin("not a url") is None and auth.page_origin("") is None and auth.page_origin(None) is None
    assert auth.page_origin("http:///path") is None  # no host, no origin
