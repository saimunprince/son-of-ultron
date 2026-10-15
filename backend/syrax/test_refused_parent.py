"""The archive's first publish (2026-10-15) listed every refused release with
no parent commit. A refused attempt records the commit it started from, like
every other attempt, so the archive's lineage has no holes."""

import asyncio

import pytest

from syrax.devloop import DevLoop
from syrax.journal import Journal
from syrax.test_devloop import PASS, git, repo


def test_a_refused_release_is_archived_with_the_commit_it_started_from(tmp_path):
    root = repo(tmp_path)
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("nothing to do", kind="conversation")
    dl = DevLoop(j, root=root, gates=lambda: PASS, task_id_provider=lambda: t, snapshot_dir=tmp_path / "rb")
    dl.begin_task()
    with pytest.raises(ValueError, match="nothing to release"):
        asyncio.run(dl.release("an empty change"))
    row = j.archive(limit=1)[0]
    assert row["decision"] == "REFUSED" and row["parent"] == git(root, "rev-parse", "HEAD") and row["head"] is None
