"""M3: the rise ledger publishes itself once a day through SYRAX's own
isolated release; a false claim that is sent back is journaled. Throwaway git
repositories, fake gates, no model."""

import asyncio
import importlib.util
import subprocess
import sys
import time
from pathlib import Path

from syrax import autonomy as auto
from syrax import ledger, rise
from syrax.devloop import JUDGES
from syrax.journal import Journal
from syrax.test_autonomy import make
from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, get_journal, reply, script, server  # noqa: F401
from syrax.verify import Gate

PASS = [Gate("ok", [sys.executable, "-c", "pass"])]
FAIL = [Gate("tests", [sys.executable, "-c", "raise SystemExit(1)"])]
ROOT = Path(__file__).resolve().parents[2]


def git(root, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


def repo(tmp_path):
    root = tmp_path / "live"
    (root / "docs").mkdir(parents=True)
    git(root, "init", "-q")
    (root / ".gitignore").write_text(".syrax/\n")
    (root / "docs" / "RISE.md").write_text("# old ledger\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return root


def test_the_ledger_is_published_through_an_isolated_release(tmp_path):
    root = repo(tmp_path)
    j = Journal(tmp_path / "j.db")
    head0 = git(root, "rev-parse", "HEAD")
    rep = asyncio.run(ledger.publish(j, root=root, gates=lambda: PASS, now=time.time()))
    assert rep["outcome"] == "COMMITTED"
    assert git(root, "rev-parse", "HEAD") != head0 and git(root, "log", "-1", "--format=%an") == "SYRAX"
    assert (root / "docs" / "RISE.md").read_text(encoding="utf-8").startswith("# SYRAX rise ledger")
    assert git(root, "status", "--porcelain") == ""
    assert not any((root / ".syrax" / "maintenance").iterdir())  # its worktree is gone
    t = j.task(rep["task_id"])
    assert t["status"] == "SUCCESS" and t["kind"] == "autonomous"
    assert j.experiments(limit=1)[0]["result"]["decision"] == "COMMITTED"
    assert not ledger.due(j)  # once a day
    assert asyncio.run(ledger.publish(j, root=root, gates=lambda: PASS))["outcome"] == "SKIPPED"


def test_a_blocked_gate_publishes_nothing_and_waits_before_retrying(tmp_path):
    root = repo(tmp_path)
    j = Journal(tmp_path / "j.db")
    now = time.time()
    head0 = git(root, "rev-parse", "HEAD")
    rep = asyncio.run(ledger.publish(j, root=root, gates=lambda: FAIL, now=now))
    assert rep["outcome"] == "ROLLED_BACK" and git(root, "rev-parse", "HEAD") == head0
    assert (root / "docs" / "RISE.md").read_text() == "# old ledger\n"
    assert j.task(rep["task_id"])["status"] == "FAILED"
    assert not ledger.due(j, now + 3600) and ledger.due(j, now + ledger.RETRY_S + 1)


def test_the_cycle_publishes_only_when_the_service_asks(tmp_path, monkeypatch):
    j, core, a = make(tmp_path, tools=["terminate"])
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    a.set_enabled(True)
    calls = []

    async def fake_publish(journal, **kw):
        calls.append(kw)
        return {"outcome": "COMMITTED"}

    monkeypatch.setattr(ledger, "publish", fake_publish)
    monkeypatch.setenv("SYRAX_PUBLISH_RISE", "0")
    assert asyncio.run(a.run_once()).outcome == "IDLE" and calls == []
    monkeypatch.setenv("SYRAX_PUBLISH_RISE", "1")
    rep = asyncio.run(a.run_once())
    assert rep.outcome == "RAN" and "published the rise ledger: COMMITTED" in rep.reason and len(calls) == 1


def test_a_false_claim_sent_back_is_journaled(script):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    script.queue = [call("journal_query", {"sql": "SELECT 1"}), reply("The limitation has been addressed."), reply("Read the journal; nothing is changed yet.")]

    async def go():
        tid = await core.submit("Improve the release tool", said="Improve the release tool", session_id=None, kind="autonomous")
        await core.wait()
        return tid

    tid = asyncio.run(go())
    rejected = [e for e in get_journal().events(tid) if e["type"] == "claim.rejected"]
    assert len(rejected) == 1 and rejected[0]["payload"]["text"] == "The limitation has been addressed."
    assert rejected[0].get("payload", {}).get("task_kind") == "autonomous"


def test_the_ledger_counts_claims_sent_back_and_its_publisher_is_a_judge(tmp_path):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("own", kind="autonomous")
    j.record_sync("claim.rejected", {"text": "has been addressed", "task_kind": "autonomous"}, task_id=t)
    j.close()
    m = {r["id"]: r for r in rise.measure(tmp_path / "j.db", time.time() + 1)["metrics"]}  # + 1: the window ends before `now`, and time.time() ticks every 15.6 ms on Windows
    assert m["claims_rejected"]["last"]["value"] == 1
    assert "backend/syrax/ledger.py" in JUDGES


def test_the_service_launcher_turns_publishing_on(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("syrax_launcher_pub", ROOT / "syrax.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name, value in (("LOG", tmp_path / "syrax.log"), ("PID_FILE", tmp_path / "syrax.pid"), ("_OUTPUT_IS_LOG", False),
                        ("setup", lambda verbose=False: None), ("check_config", lambda: None),
                        ("port_in_use", lambda port: False), ("ui_is_stale", lambda: False)):
        monkeypatch.setattr(mod, name, value)
    for var in ("SYRAX_PUBLISH_RISE", "SYRAX_ISOLATE"):
        monkeypatch.setenv(var, "placeholder")  # so monkeypatch restores their absence after launch() sets them
        monkeypatch.delenv(var)
    monkeypatch.setenv("SYRAX_OPEN_UI", "0")
    seen = []

    class Fake:
        def __init__(self, name, cmd, cwd, log):
            self.name, self.proc = name, type("P", (), {"returncode": 0})()
            seen.append(__import__("os").environ.get("SYRAX_PUBLISH_RISE"))

        def alive(self):
            return self.name != "core"

        def stop(self):
            pass

    monkeypatch.setattr(mod, "Component", Fake)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    assert mod.launch(dev=False, service=True) == 0 and seen[0] == "1"
