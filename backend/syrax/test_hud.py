"""The desktop HUD (hud/) is served by SYRAX itself, from its own origin, so the
Electron shell talks to the core without a foreign-origin exception; only the
two page files are served, and the HUD's link module is part of the gate."""

from pathlib import Path

from fastapi.testclient import TestClient

from syrax import server, verify

ROOT = Path(__file__).resolve().parents[2]


def test_the_hud_and_its_link_are_served_and_nothing_else():
    c = TestClient(server.app)
    page = c.get("/hud")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert "<title>SYRAX</title>" in page.text and 'src="link.js"' in page.text
    js = c.get("/hud/link.js")
    assert js.status_code == 200 and "SyraxLink" in js.text and js.headers["content-type"].startswith("text/javascript")
    assert c.get("/hud/main.js").status_code == 404  # the Electron shell is not a web page
    assert c.get("/hud/..%2Fsyrax.py").status_code == 404


def test_the_servers_own_origin_is_allowed_and_a_foreign_one_still_is_not():
    own = f"http://127.0.0.1:{server.PORT}"
    assert own in server.ALLOWED_ORIGINS and f"http://localhost:{server.PORT}" in server.ALLOWED_ORIGINS
    c = TestClient(server.app)
    assert c.post("/upload?name=a.txt", content=b"12", headers={"origin": own}).status_code != 403
    assert c.post("/upload?name=a.txt", content=b"12", headers={"origin": "http://evil.example"}).status_code == 403


def test_the_hud_link_has_its_own_gate_and_the_page_finds_the_core_from_disk():
    names = [g.name for g in verify.default_gates()]
    assert "hud_test" in names and names.index("hud_test") < names.index("diff_scan")
    html = (ROOT / "hud" / "hud.html").read_text(encoding="utf-8")
    assert "ws://127.0.0.1:8765/ws" in html and "location.origin.replace(/^http/, 'ws') + '/ws'" in html
    assert "HTTP_BASE + '/tts'" in html  # SYRAX's own voice, not the browser's
    assert "const API = " not in html  # the invented POST backend is gone
