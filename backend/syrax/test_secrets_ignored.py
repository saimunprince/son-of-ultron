"""2026-10-29: backend/config/journal.db.key (the journal chain's HMAC key, made on first use) showed in `git status`
as untracked: the repository is public, and one `git add -A` would have published it. Every file that holds a secret
or the evidence is ignored by git."""

import subprocess

from syrax.journal import BACKEND_ROOT

SECRET_FILES = ("brains.json", "brains.tmp", "ws.token", "config.toml", "mcp.json", "memory.json", "journal.db",
                "journal.db-wal", "journal.db-shm", "journal.db.key", "journal.db.owner", "backups/x/brains.json", "portal.token")


def test_every_secret_file_is_ignored_by_git():
    repo = BACKEND_ROOT.parent
    paths = [f"backend/config/{n}" for n in SECRET_FILES]
    r = subprocess.run(["git", "check-ignore", "--no-index", *paths], cwd=repo, capture_output=True, text=True)
    ignored = set(r.stdout.split())
    assert ignored == set(paths), sorted(set(paths) - ignored)
