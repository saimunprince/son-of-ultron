"""M3: the capability matrix is regenerated with the rise ledger, from a
JUnit report of the worktree, live probes of the running service and the
journal's last verification; a probe never takes the human's briefing.
Throwaway repositories, a local HTTP stub, fake gates, no model."""

import asyncio
import http.server
import json
import os
import socket
import threading
import time

from syrax import capmatrix, ledger, probe
from syrax.devloop import JUDGES
from syrax.journal import Journal
from syrax.test_bridge import ORIGIN, TestClient, recv_until, script, server  # noqa: F401
from syrax.test_ledger_publish import PASS, git, repo

JUNIT = """<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" errors="0" failures="0" skipped="0" tests="2" time="1.5">
<testcase classname="syrax.test_bridge" name="test_hello_and_brain_panel" time="0.1"/>
<testcase classname="syrax.test_verify" name="test_gate" time="0.1"/>
</testsuite></testsuites>"""


class Stub(http.server.BaseHTTPRequestHandler):
    """The running service as the probes see it."""

    def log_message(self, *a):
        pass

    def _send(self, body: bytes, ctype="application/json"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(json.dumps({"name": "SYRAX", "status": "online"}).encode())
        elif self.path.startswith("/self"):
            self._send(json.dumps({"components": [{"component": "Journal → WAL"}]}).encode())
        else:
            self._send(b"<html><head><title>SYRAX</title></head></html>", "text/html")

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path == "/tts":
            self._send(b"ID3-fake-audio", "audio/mpeg")
        else:
            heard = "SYRAX. Open the journal." if body == b"ID3-fake-audio" else ""
            self._send(json.dumps({"text": heard, "engine": "stub"}).encode())


def stub_service():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_the_probes_report_what_the_service_answers_and_why_one_failed(tmp_path):
    srv, base = stub_service()
    try:
        (tmp_path / "syrax.pid").write_text(str(os.getpid()))
        eps = {"http": base, "ui": base + "/", "ws": f"ws://127.0.0.1:{closed_port()}/ws?probe=1", "origin": "http://localhost:3001"}
        ev = probe.collect(eps, pid_file=tmp_path / "syrax.pid")
    finally:
        srv.shutdown()
    assert ev["process"] == {"pid": os.getpid(), "pid_alive": True}
    assert ev["http"]["self_structure"]["mojibake_count"] == 0 and ev["ui"] == {"status": 200, "title": "SYRAX"}
    assert ev["voice"]["roundtrip_pass"] is True and ev["ws"]["error"]  # nothing listens there: said, not passed
    live = capmatrix.live_checks(ev, None, {"counts": {}, "journal_wal": "wal", "skills_verified": []})
    assert {k: live[k][0] for k in ("health", "ui", "process", "tts", "stt_roundtrip", "self_model", "ws_hello")} == {
        "health": "pass", "ui": "pass", "process": "pass", "tts": "pass", "stt_roundtrip": "pass", "self_model": "pass", "ws_hello": "fail"}


def test_a_missing_or_broken_pid_file_is_no_evidence(tmp_path):
    assert probe.process(tmp_path / "none.pid") == {}
    (tmp_path / "bad.pid").write_text("not a pid")
    assert probe.process(tmp_path / "bad.pid") == {}


def test_the_probes_find_the_service_where_it_was_started(monkeypatch):
    monkeypatch.setenv("SYRAX_PORT", "8765")
    monkeypatch.setenv("SYRAX_UI_PORT", "3001")
    monkeypatch.setenv("SYRAX_ALLOWED_ORIGINS", "http://localhost:3001,http://127.0.0.1:3001")
    assert probe.endpoints() == {"http": "http://127.0.0.1:8765", "ws": "ws://127.0.0.1:8765/ws?probe=1",
                                 "ui": "http://localhost:3001", "origin": "http://localhost:3001"}


def booted(ws):
    """Everything a session gets until it settles (the state after "booting")."""
    seen = []
    while True:
        _, got = recv_until(ws, "state")
        seen += got
        if got[-1].get("state") != "booting":
            return seen


def test_a_probe_session_never_takes_the_humans_daily_briefing(script, monkeypatch):
    monkeypatch.setenv("SYRAX_BRIEFING", "1")
    client = TestClient(server.app)
    with client.websocket_connect("/ws?probe=1", headers=ORIGIN) as ws:
        seen = booted(ws)
    assert "hello" in [e["type"] for e in seen] and "briefing" not in [e["type"] for e in seen]
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        seen = booted(ws)
    assert "briefing" in [e["type"] for e in seen]  # still there for the human


def matrix_repo(tmp_path):
    root = repo(tmp_path)
    (root / "docs" / "system_map.json").write_text(json.dumps({"components": []}))
    (root / "docs" / "CAPABILITY_MATRIX.md").write_text("# old matrix\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "map")
    return root


def fake_junit(wt, xml):
    xml.write_text(JUNIT, encoding="utf-8")
    return True


def fake_probe():
    return {"http": {"health": {"json": {"status": "online"}}}, "ui": {"status": 200, "title": "SYRAX"},
            "process": {"pid": 1, "pid_alive": True}}


def test_the_matrix_is_published_with_the_ledger_from_tests_probes_and_the_last_gate(tmp_path):
    root = matrix_repo(tmp_path)
    j = Journal(tmp_path / "j.db")
    rep = asyncio.run(ledger.publish(j, root=root, gates=lambda: PASS, now=time.time(), matrix=True, junit=fake_junit, prober=fake_probe))
    assert rep["outcome"] == "COMMITTED" and rep["matrix"] and sum(rep["matrix"].values()) == len(capmatrix.CAPABILITIES)
    text = (root / "docs" / "CAPABILITY_MATRIX.md").read_text(encoding="utf-8")
    assert text.startswith("# SYRAX capability matrix") and "Test suite: 2 passed" in text and "journal `j.db`" in text
    assert "Self-published evidence" in text and "Code-change benchmark per brain" in text
    assert sorted(git(root, "show", "--name-only", "--format=", "HEAD").split()) == ["docs/ARCHIVE.md", "docs/CAPABILITY_MATRIX.md", "docs/DEVLOG.md", "docs/RISE.md"]
    assert git(root, "log", "-1", "--format=%s").endswith(ledger.SUMMARY_WITH_MATRIX)
    assert git(root, "status", "--porcelain") == ""
    assert not any((root / ".syrax" / "maintenance").iterdir())  # no worktree and no JUnit file left behind
    assert "capability matrix" in j.task(rep["task_id"])["result"]


def test_without_a_test_report_the_old_matrix_stays_and_the_ledger_still_lands(tmp_path):
    root = matrix_repo(tmp_path)
    j = Journal(tmp_path / "j.db")
    rep = asyncio.run(ledger.publish(j, root=root, gates=lambda: PASS, now=time.time(), matrix=True,
                                     junit=lambda wt, xml: False, prober=fake_probe))
    assert rep["outcome"] == "COMMITTED" and rep["matrix"] is None
    assert (root / "docs" / "CAPABILITY_MATRIX.md").read_text() == "# old matrix\n"
    assert sorted(git(root, "show", "--name-only", "--format=", "HEAD").split()) == ["docs/ARCHIVE.md", "docs/DEVLOG.md", "docs/RISE.md"]


def test_the_gate_row_reads_the_journals_last_verification():
    v = {"status": "GREEN", "gates": [{"name": "pytest", "status": "PASS"}, {"name": "tsc", "status": "PASS"}, {"name": "eslint", "status": "PASS"},
                                      {"name": "node_test", "status": "PASS"}, {"name": "next_build", "status": "PASS"}]}
    g = capmatrix.gate_from_verification(v)
    assert g == {"status": "GREEN", "gates": {"pytest": "PASS", "tsc": "PASS", "eslint": "PASS", "node_test": "PASS", "next_build": "PASS"}}
    live = capmatrix.live_checks(None, g, {"counts": {}, "journal_wal": "wal", "skills_verified": []})
    assert live["gate"][0] == "pass" and live["gate_frontend"][0] == "pass"
    assert capmatrix.gate_from_verification(None) is None


def test_the_new_rows_count_their_runtime_evidence(tmp_path):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("[AUTONOMOUS OBJECTIVE] x", kind="autonomous")
    j.record_sync("isolation.started", {"worktree": "w"}, task_id=t)
    j.record_sync("commit.created", {"commit": "abc", "files": ["a"]}, task_id=t)
    m = j.start_task_sync("[MAINTENANCE] publish the rise ledger (docs/RISE.md) from the journal", kind="autonomous")
    j.record_sync("final", {"text": "RISE ledger published"}, task_id=m)
    j.record_sync("task.completed", {"status": "SUCCESS", "result": "RISE ledger published"}, task_id=m)
    j.record_sync("codebench.completed", {"brain": "alpha", "graded": 4, "passed": 2})
    j.record_sync("codebench.completed", {"brain": "beta", "graded": 0, "passed": 0})  # a brain that never answered
    j.close()
    counts = capmatrix.read_journal(tmp_path / "j.db")["counts"]
    assert (counts["isolated_commits"], counts["ledger_published"], counts["codebench_runs"]) == (1, 1, 1)


def test_the_probe_is_a_judge():
    assert "backend/syrax/probe.py" in JUDGES
