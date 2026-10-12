"""Dropping a file on the UI (feature catalog: file_processor): /upload keeps
it in the workspace under a safe name, refuses foreign origins, empty and
oversized files, and journals it."""

from syrax import server as server_mod
from syrax.test_bridge import ORIGIN, TestClient, get_journal, script, server  # noqa: F401


def test_a_dropped_file_is_kept_under_a_safe_name(script, tmp_path, monkeypatch):
    monkeypatch.setattr(server_mod, "upload_dir", lambda: tmp_path / "uploads")
    c = TestClient(server.app)
    r = c.post("/upload?name=..%2F..%2Fevil%20name%3F.txt", content=b"hello", headers={**ORIGIN, "Content-Type": "application/octet-stream"})
    assert r.status_code == 200
    saved = r.json()["path"]
    assert saved.endswith("-evil name_.txt") and r.json()["bytes"] == 5
    files = list((tmp_path / "uploads").iterdir())
    assert len(files) == 1 and files[0].read_bytes() == b"hello" and str(files[0]) == saved
    ev = [e for e in get_journal().recent_events(50) if e["type"] == "file.uploaded"]
    assert ev and ev[-1]["payload"]["path"] == saved


def test_refusals(script, tmp_path, monkeypatch):
    monkeypatch.setattr(server_mod, "upload_dir", lambda: tmp_path / "uploads")
    monkeypatch.setattr(server_mod, "UPLOAD_MAX_BYTES", 4)
    c = TestClient(server.app)
    assert c.post("/upload?name=a.txt", content=b"", headers=ORIGIN).status_code == 400
    assert c.post("/upload?name=a.txt", content=b"12345", headers=ORIGIN).status_code == 413
    assert c.post("/upload?name=a.txt", content=b"12", headers={"origin": "http://evil.example"}).status_code == 403
    assert not (tmp_path / "uploads").exists()
