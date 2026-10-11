"""Three gaps M1's live proof exposed (2026-10-11): a stopped task's gate
kept running; one attempt re-released the same blocked change five times; the
gate verdict named the running tree's head instead of the checked tree's."""

import asyncio
import subprocess
import sys
import threading
import time

import pytest

from syrax import verify as V
from syrax.devloop import DevLoop
from syrax.journal import Journal
from syrax.verify import Gate

PLAN = {"why": "objective", "risk": "mod callers", "tests": "test_mod.py"}


def git(root, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "backend" / "syrax").mkdir(parents=True)
    git(root, "init", "-q")
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 1\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return root


def slow_writer(marker):
    """A gate that would write a marker after 4 s: if the marker exists, it was not stopped."""
    return [sys.executable, "-c", f"import time, pathlib; time.sleep(4); pathlib.Path(r'{marker}').write_text('ran')"]


def test_a_cancelled_gate_stops_with_its_process(tmp_path):
    marker = tmp_path / "ran.txt"
    cancel = threading.Event()
    threading.Timer(0.5, cancel.set).start()
    t0 = time.monotonic()
    r = V.run_gate(Gate("slow", slow_writer(marker)), cancel)
    assert r.status == "NOT_VERIFIED" and "cancelled" in r.evidence and time.monotonic() - t0 < 4
    time.sleep(4.5)
    assert not marker.exists()  # the process was killed, not left running


def test_stopping_a_release_stops_its_gate_and_journals_no_verdict(tmp_path):
    root = repo(tmp_path)
    marker = tmp_path / "ran.txt"
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("improve mod", kind="conversation")
    dl = DevLoop(j, root=root, gates=lambda: [Gate("slow", slow_writer(marker)), Gate("never", [sys.executable, "-c", "pass"])],
                 task_id_provider=lambda: t, snapshot_dir=tmp_path / "rb")
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 2\n")

    async def go():
        rel = asyncio.ensure_future(dl.release("bump"))
        await asyncio.sleep(1.0)
        rel.cancel()
        with pytest.raises(asyncio.CancelledError):
            await rel

    asyncio.run(go())
    time.sleep(4.5)
    assert not marker.exists() and j.verifications() == []


def test_the_same_failure_twice_refuses_a_third_release(tmp_path):
    root = repo(tmp_path)
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("[AUTONOMOUS OBJECTIVE] x", kind="autonomous")
    fail = [Gate("pytest", [sys.executable, "-c", "print('FAILED syrax/test_voice.py::test_tts_endpoint - 403'); raise SystemExit(1)"])]
    dl = DevLoop(j, root=root, gates=lambda: fail, task_id_provider=lambda: t, snapshot_dir=tmp_path / "rb")
    for value in (2, 3):
        (root / "backend" / "syrax" / "mod.py").write_text(f"VALUE = {value}\n")
        assert asyncio.run(dl.release("try", PLAN))["outcome"] == "ROLLED_BACK"
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 4\n")
    with pytest.raises(ValueError, match="failed twice in this task with the same failures"):
        asyncio.run(dl.release("try again", PLAN))
    assert len(j.verifications()) == 2  # no third gate run
    assert j.experiments(limit=1)[0]["result"]["decision"] == "REFUSED"


def test_different_failures_do_not_refuse(tmp_path):
    root = repo(tmp_path)
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("[AUTONOMOUS OBJECTIVE] x", kind="autonomous")
    outputs = iter(["FAILED syrax/test_a.py::test_one", "FAILED syrax/test_b.py::test_two", "FAILED syrax/test_c.py::test_three"])
    dl = DevLoop(j, root=root, gates=lambda: [Gate("pytest", [sys.executable, "-c", f"print('{next(outputs)}'); raise SystemExit(1)"])],
                 task_id_provider=lambda: t, snapshot_dir=tmp_path / "rb")
    for value in (2, 3, 4):
        (root / "backend" / "syrax" / "mod.py").write_text(f"VALUE = {value}\n")
        assert asyncio.run(dl.release("try", PLAN))["outcome"] == "ROLLED_BACK"


def test_the_verdict_names_the_checked_trees_revision(tmp_path):
    root = repo(tmp_path)
    head = git(root, "rev-parse", "HEAD")
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("improve mod", kind="conversation")
    dl = DevLoop(j, root=root, gates=lambda: [Gate("ok", [sys.executable, "-c", "pass"])], task_id_provider=lambda: t, snapshot_dir=tmp_path / "rb")
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 2\n")
    assert asyncio.run(dl.release("bump"))["outcome"] == "COMMITTED"
    assert j.verifications()[0]["git_head"] == head  # the tree it checked, not the repository the code runs from
