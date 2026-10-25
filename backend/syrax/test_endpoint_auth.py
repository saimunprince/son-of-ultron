"""Audit 2026-10-25: /self and /voice answered anyone on the machine while /stt wanted an allowed Origin or the token.
Now /voice and the /self sections that describe this machine and checkout (summary, structure, runtime, all) follow
the rule /stt follows; the story sections of /self (test_bridge reads `behavior` with no Origin) and /health stay
readable, and so does the HUD's own path (Electron's main.js probes GET /hud/ with no Origin; the HUD never reads
/self or /voice). probe.py presents the UI's Origin, so it reads the structure as before."""

from types import SimpleNamespace

from syrax import auth, probe, server
from syrax.selfmodel import SECTIONS
from syrax.test_bridge import ORIGIN, TestClient, script  # noqa: F401

MACHINE = {"summary", "structure", "runtime", "all"}
HUD_ORIGIN = {"origin": f"http://127.0.0.1:{server.PORT}"}


def snapshot(section):
    if section not in SECTIONS:
        raise ValueError(f"unknown section {section!r}")
    return {section: {"stub": True}}


def client_with_stub_core(monkeypatch):
    monkeypatch.setattr(server, "get_core", lambda: SimpleNamespace(selfmodel=SimpleNamespace(snapshot=snapshot)))
    monkeypatch.setattr(auth, "token", lambda path=None: "SECRET")
    return TestClient(server.app)


def test_self_machine_sections_need_an_allowed_origin_or_the_token(monkeypatch):
    c = client_with_stub_core(monkeypatch)
    for q in ("", "?section=summary", "?section=structure", "?section=runtime", "?section=all"):
        r = c.get(f"/self{q}")
        assert r.status_code == 403 and "token" in r.json()["detail"], q
    assert c.get("/self", headers=ORIGIN).status_code == 200
    assert c.get("/self?section=runtime&token=SECRET").status_code == 200
    assert c.get("/self?section=runtime", headers={"x-syrax-token": "SECRET"}).status_code == 200
    assert c.get("/self?section=runtime&token=wrong").status_code == 403
    assert c.get("/self?section=runtime&token=SECRET", headers={"origin": "http://evil.example"}).status_code == 403


def test_story_sections_health_and_the_hud_path_stay_readable(monkeypatch):
    c = client_with_stub_core(monkeypatch)
    for s in sorted(set(SECTIONS) - MACHINE):
        assert c.get(f"/self?section={s}").status_code == 200, s  # the contract test_bridge reads `behavior` this way
    assert c.get("/self?section=nope").status_code == 400  # an unknown section is 400 as before, Origin or not
    assert c.get("/health").status_code == 200
    assert c.get("/hud/").status_code == 200  # Electron main.js liveness probe: GET, no Origin
    assert c.get("/self", headers=HUD_ORIGIN).status_code == 200  # the HUD's own origin, were it ever to read /self
    assert server.SELF_OPEN_SECTIONS | MACHINE == set(SECTIONS)  # every section has a side


def test_voice_needs_an_allowed_origin_or_the_token(monkeypatch):
    c = client_with_stub_core(monkeypatch)
    assert c.get("/voice").status_code == 403
    assert c.get("/voice", headers={"origin": "http://evil.example"}).status_code == 403
    ok = c.get("/voice", headers=ORIGIN)
    assert ok.status_code == 200 and {"tts_voice", "stt", "whisper"} <= set(ok.json())
    assert c.get("/voice?token=SECRET").status_code == 200
    assert c.get("/voice", headers={"x-syrax-token": "SECRET"}).status_code == 200


def test_the_probe_presents_the_ui_origin_so_it_still_reads_the_structure(monkeypatch):
    c = client_with_stub_core(monkeypatch)
    origin = probe.endpoints()["origin"]
    assert origin in server.ALLOWED_ORIGINS
    assert c.get("/self?section=structure", headers={"origin": origin}).status_code == 200
