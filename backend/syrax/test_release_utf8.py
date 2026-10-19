"""Live 2026-10-19: the daily ledger release failed twice over on Windows. DevLoop's git helper read the diff as
cp1252, a UTF-8 byte (0x90) killed the reader thread, stdout came back None, and the release died with "unsupported
operand type(s) for +: 'NoneType' and 'str'"; once that was read right, the rollback snapshot could not be written,
"'charmap' codec can't encode character '\\u2190'". Both read and write UTF-8 now, and a failed publish names where."""

import asyncio
import time

from syrax import ledger, rise
from syrax.devloop import DevLoop, _git
from syrax.journal import Journal
from syrax.test_devloop import PASS, git, repo

TEXT = "arrows \u2190 \u2192, a degree \u00b0 and an ellipsis \u2026\n"


def test_git_output_with_utf8_is_read_and_a_snapshot_with_it_is_written(tmp_path):
    root = repo(tmp_path)
    (root / "docs" / "notes.md").write_bytes(TEXT.encode("utf-8"))
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "notes \u2190 \u2192")
    assert _git(["log", "-1", "--format=%s"], root).stdout.strip() == "notes \u2190 \u2192"
    (root / "docs" / "notes.md").write_bytes(("changed \u2190\n" + TEXT).encode("utf-8"))
    (root / "docs" / "new.md").write_bytes(TEXT.encode("utf-8"))
    dl = DevLoop(Journal(tmp_path / "j.db"), root=root, gates=lambda: PASS)
    info = {"head": git(root, "rev-parse", "HEAD"), "diff": _git(["diff"], root).stdout, "untracked": ["docs/new.md"]}
    assert "changed \u2190" in info["diff"]
    body = dl.snapshot(info).read_bytes().decode("utf-8")
    assert "changed \u2190" in body and "# untracked: docs/new.md" in body and TEXT in body


def test_a_failed_publish_names_the_exception_and_where(tmp_path, monkeypatch):
    def broken(*a, **kw):
        return None + "x"

    monkeypatch.setattr(rise, "measure", broken)
    root = repo(tmp_path)
    rep = asyncio.run(ledger.publish(Journal(tmp_path / "j.db"), root=root, gates=lambda: PASS, now=time.time(), force=True))
    assert rep["outcome"] == "FAILED"
    assert rep["error"].startswith("TypeError: unsupported operand type(s) for +: 'NoneType' and 'str' at test_release_utf8.py:")
