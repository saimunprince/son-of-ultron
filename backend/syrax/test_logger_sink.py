"""app/logger.py added a logs/<timestamp>.log sink at import in every process, so each pytest run left a file
in the production backend/logs (2,699 files, most of them empty) and fake-brain tracebacks there read like
production failures. Tests log to stderr only; the server keeps its file, created on its first line."""

import app.logger as applog
from app.logger import define_log_level


def logs_in(root):
    d = root / "logs"
    return sorted(d.iterdir()) if d.exists() else []


def test_a_test_process_leaves_no_log_file(tmp_path, monkeypatch):
    monkeypatch.setattr(applog, "PROJECT_ROOT", tmp_path)
    try:
        define_log_level().error("a fake brain failed")
        assert logs_in(tmp_path) == []
    finally:
        define_log_level()  # back to the session's sinks (closes any file it opened)


def test_the_server_keeps_its_file_and_creates_it_on_the_first_line(tmp_path, monkeypatch):
    monkeypatch.setattr(applog, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(applog, "_testing", lambda: False)
    try:
        log = define_log_level(name="srv")
        assert logs_in(tmp_path) == []  # nothing logged yet: no empty file
        log.info("server started")
    finally:
        define_log_level()
    files = logs_in(tmp_path)
    assert len(files) == 1 and files[0].name.startswith("srv_")
    assert "server started" in files[0].read_text(encoding="utf-8")
