"""Self-model tests: every value must match the real system, or be None."""

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from syrax.journal import Journal
from syrax.selfmodel import REPO_ROOT, SECTIONS, SelfInspectTool, SelfModel, render


def journal(tmp_path) -> Journal:
    return Journal(tmp_path / "j.db")


def seed(j: Journal):
    ok = j.start_task_sync("good")
    j.record_sync("tool.started", {"id": "a", "name": "python_execute", "args": {}}, task_id=ok)
    j.record_sync("tool.completed", {"id": "a", "name": "python_execute", "ok": True, "output": "1"}, task_id=ok)
    j.record_sync("final", {"text": "done"}, task_id=ok)
    j.record_sync("task.completed", {"status": "SUCCESS"}, task_id=ok)
    bad = j.start_task_sync("bad")
    j.record_sync("tool.started", {"id": "b", "name": "desktop", "args": {"action": "open"}}, task_id=bad)
    j.record_sync("tool.failed", {"id": "b", "name": "desktop", "ok": False, "output": "Error: no"}, task_id=bad)
    j.record_sync("task.failed", {"error": "desktop broke"}, task_id=bad)
    return ok, bad


def test_identity_version_is_the_real_git_head(tmp_path):
    m = SelfModel(journal(tmp_path))
    ident = m.identity()
    real = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()
    assert ident["name"] == "SYRAX" and ident["version"] == real
    assert ident["principles"] and ident["process_uptime_s"] >= 0


def test_structure_reads_repo_and_system_map(tmp_path):
    m = SelfModel(journal(tmp_path))
    s = m.structure()
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()
    assert s["git"]["head"] == head and s["git"]["branch"]
    assert s["git"]["recent_commits"][0]["hash"] == head[:7]
    assert s["files"]["backend/syrax"]["tests"] >= 7 and s["files"]["backend/syrax"]["lines"] > 1000
    names = {c["component"] for c in s["components"]}
    assert {"Journal", "Core", "Verification gate", "SyraxAgent"} <= names
    assert s["system_map"]["present"] is True


def test_structure_without_git_or_map_reports_none_not_fakes(tmp_path):
    m = SelfModel(journal(tmp_path), repo_root=tmp_path, system_map=tmp_path / "missing.json")
    s = m.structure()
    assert s["git"]["head"] is None and s["git"]["dirty_files"] is None and s["git"]["recent_commits"] == []
    assert s["components"] == [] and s["system_map"]["present"] is False
    assert m.identity()["version"] is None


def test_runtime_matches_the_machine(tmp_path):
    j = journal(tmp_path)
    m = SelfModel(j)
    m.brains_provider = lambda: {"active": "ollama", "providers": [{"id": "ollama", "status": "ready"}, {"id": "gemini", "status": "no-key"}]}
    m.running_provider = lambda: {"task_id": "t1", "goal": "x"}
    r = m.runtime()
    mem = {ln.split(":")[0]: int(ln.split()[1]) // 1024 for ln in Path("/proc/meminfo").read_text().splitlines()}
    assert r["memory_mb"]["total_mb"] == mem["MemTotal"]
    assert r["cpu"]["cores"] == __import__("os").cpu_count() and len(r["cpu"]["load_1_5_15"]) == 3
    assert r["journal"]["path"] == str(j.path) and r["journal"]["bytes"] > 0
    assert r["brains"] == {"active": "ollama", "ready": ["ollama"], "cooldown": [], "needs_key": ["gemini"]}
    assert r["running_task"] == {"task_id": "t1", "goal": "x"} and r["gpu"] is None


def test_behavior_is_derived_from_the_journal(tmp_path):
    j = journal(tmp_path)
    ok, bad = seed(j)
    j.record_verification_sync({"status": "BLOCKED", "gates": [{"name": "pytest", "status": "FAIL", "required": True}]})
    b = SelfModel(j).behavior()
    assert b["tasks_by_status"] == {"SUCCESS": 1, "FAILED": 1} and b["tasks_total"] == 2 and b["success_rate"] == 0.5
    assert [t["task_id"] for t in b["recent_tasks"]] == [bad, ok]
    assert b["recent_failures"][0]["error"] == "desktop broke"
    assert b["verifications"]["last"]["status"] == "BLOCKED" and b["verifications"]["blocked"] == 1


def test_capability_registry_crosses_tools_with_evidence(tmp_path):
    j = journal(tmp_path)
    seed(j)
    m = SelfModel(j)
    m.tools_provider = lambda: ["python_execute", "desktop", "remember", "self_inspect"]
    caps = {c["capability"]: c for c in m.capabilities()}
    assert caps["python_execute"]["status"] == "VERIFIED" and caps["python_execute"]["confidence"] == 1.0 and caps["python_execute"]["uses"] == 1
    assert caps["desktop"]["status"] == "FAILING" and caps["desktop"]["failures"] == 1 and caps["desktop"]["last_failed"]
    assert caps["remember"]["status"] == "NOT_TESTED" and caps["remember"]["confidence"] is None
    assert caps["self_inspect"]["implementation"].endswith("selfmodel.py")
    # evidence for a tool that is no longer registered
    m.tools_provider = lambda: ["python_execute"]
    caps = {c["capability"]: c for c in m.capabilities()}
    assert caps["desktop"]["status"] == "MISSING" and caps["desktop"]["registered"] is False


def test_weaknesses_are_derived_with_evidence_pointers(tmp_path):
    j = journal(tmp_path)
    seed(j)
    old = Journal(tmp_path / "j.db", boot_id="dead", recover=False)
    t = old.start_task_sync("risky")
    old.record_sync("tool.started", {"id": "c", "name": "python_execute", "args": {"code": "rm"}}, task_id=t)
    old.close()
    j2 = Journal(tmp_path / "j.db")  # recovery marks it UNCERTAIN
    m = SelfModel(j2)
    m.tools_provider = lambda: ["python_execute", "desktop", "recall"]
    w = m.weaknesses()
    details = [x["detail"] for x in w]
    assert any("desktop failed on its last use" in d for d in details)
    assert any("recall has never been used" in d for d in details)
    assert any("UNCERTAIN operation" in d and t in d for d in details)
    assert all(x["evidence"] for x in w)
    assert any(x["kind"] == "known_limitation" for x in w)  # from docs/system_map.json


def test_snapshot_sections_and_json_safety(tmp_path):
    m = SelfModel(journal(tmp_path))
    for sec in SECTIONS:
        json.dumps(m.snapshot(sec), default=str)
    with pytest.raises(ValueError):
        m.snapshot("soul")
    s = m.snapshot("summary")
    assert set(s) >= {"identity", "tasks_by_status", "capabilities", "weaknesses", "runtime", "known_limitations"}
    full = m.snapshot("all")
    assert set(full) == {"generated", "identity", "structure", "runtime", "behavior", "capabilities", "weaknesses"}


def test_self_inspect_tool(tmp_path):
    tool = SelfInspectTool()
    r = asyncio.run(tool.execute())
    assert r.error and "unavailable" in r.error
    tool.model = SelfModel(journal(tmp_path))
    r = asyncio.run(tool.execute(section="identity"))
    assert not r.error and '"name": "SYRAX"' in r.output
    r = asyncio.run(tool.execute(section="nope"))
    assert r.error and "unknown section" in r.error
    assert render({"x": "y" * 10}, limit=5).endswith("single section]")
