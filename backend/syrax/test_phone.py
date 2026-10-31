"""phone (the Ultron comparison of 2026-10-31): a phone on the WiFi may watch SYRAX and press the emergency stop,
nothing more. Off by default; its own token, never the core's; every data route refuses without it."""

import asyncio
import types

from fastapi.testclient import TestClient

from syrax import auth, phone


class FakeCore:
    def __init__(self):
        self.stopped = []
        self.busy = True
        self.current = types.SimpleNamespace(goal="sort the downloads folder", kind="conversation", task_id="t1")
        self.autonomy = types.SimpleNamespace(status=lambda: {"enabled": True, "level": 3, "state": {"state": "WAITING"},
                                                              "autonomous_today": 4, "daily_tasks": 40, "estop": None})
        self.journal = types.SimpleNamespace(tasks=lambda limit=6: [{"goal": "g" * 300, "status": "SUCCESS", "kind": "autonomous", "updated": 1.0}])


def client(tmp_path):
    core = FakeCore()

    async def stop(c, note="", who=""):
        c.stopped.append((note, who))

    tok = tmp_path / "phone.token"
    return TestClient(phone.build_app(lambda: core, stop, token_path=tok)), core, auth.token(tok)


def test_off_by_default_and_saved_by_the_owner(tmp_path):
    f = tmp_path / "phone.json"
    assert phone.settings(f) == {"enabled": False, "port": phone.PORT}
    assert phone.save(True, f)["enabled"] is True
    f.write_text("{broken")
    assert phone.settings(f)["enabled"] is False


def test_the_page_has_no_data_and_data_needs_the_token(tmp_path):
    c, core, tok = client(tmp_path)
    page = c.get("/")
    assert page.status_code == 200 and "EMERGENCY STOP" in page.text and "sort the downloads" not in page.text
    assert c.get("/status").status_code == 401
    assert c.get("/status", headers={auth.HEADER: "wrong"}).status_code == 401
    assert c.post("/estop").status_code == 401 and core.stopped == []
    d = c.get("/status", headers={auth.HEADER: tok}).json()
    assert d["running"]["goal"] == "sort the downloads folder" and d["autonomy"]["level"] == 3
    assert len(d["tasks"][0]["goal"]) == 120


def test_estop_with_the_token_stops_and_nothing_else_exists(tmp_path):
    c, core, tok = client(tmp_path)
    assert c.post("/estop", headers={auth.HEADER: tok}).json() == {"stopped": True}
    assert core.stopped and core.stopped[0][1].startswith("phone ")
    routes = {(m, r.path) for r in c.app.routes for m in (getattr(r, "methods", None) or set())}
    assert routes == {("GET", "/"), ("GET", "/status"), ("POST", "/estop")}  # no docs, no request, no clear, no settings


def test_the_phone_token_is_not_the_cores(tmp_path):
    assert auth.token(tmp_path / "phone.token") != auth.token(tmp_path / "ws.token")
    link = phone.link(host="192.168.1.5", port=8770, token_path=tmp_path / "phone.token")
    assert link.startswith("http://192.168.1.5:8770/#t=")
