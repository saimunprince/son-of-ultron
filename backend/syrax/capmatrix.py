"""The capability matrix, generated from evidence instead of typed.

Every row's status is computed from four sources: the journal (tool outcomes,
the latest quality run, verifications, skills), a JUnit report of the test
suite, an evidence file from the audit script (health, UI, WebSocket hello,
voice round trip, self-model probes) and a gate report. The only
hand-maintained part is CAPABILITIES: which tools, tests, quality cases and
live checks speak for each capability. Rules, strict, in this order:

  MISSING ............................................ RED
  PLANNED ............................................ UNVERIFIED (not built)
  a mapped test failed / latest quality case failed /
  a live check failed hard ........................... RED
  a live check failed for an external cause .......... BLOCKED
  needs a human and none attested .................... UNVERIFIED
  no passing test, or no runtime evidence ............ UNVERIFIED
  tests pass AND runtime evidence within WINDOW_DAYS
  AND failure share <= MAX_FAIL AND CURRENT .......... GREEN
  otherwise .......................................... YELLOW

    python -m syrax.capmatrix --journal config/journal.db --junit ../docs/evidence/<d>/pytest.xml \
        --evidence ../docs/evidence/<d>/evidence-run1.json --gate ../docs/evidence/<d>/gate.txt \
        --out ../docs/CAPABILITY_MATRIX.md
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from syrax.journal import BACKEND_ROOT, DEFAULT_FILE

REPO_ROOT = BACKEND_ROOT.parent
WINDOW_DAYS = 7
MAX_FAIL = 0.25
CURRENT, PARTIAL, PLANNED, MISSING = "CURRENT", "PARTIAL", "PLANNED", "MISSING"
GREEN, YELLOW, RED, BLOCKED, UNVERIFIED = "GREEN", "YELLOW", "RED", "BLOCKED", "UNVERIFIED"
ORDER = (GREEN, YELLOW, RED, BLOCKED, UNVERIFIED)


@dataclass
class Capability:
    id: str
    label: str
    implementation: str
    where: str
    tools: List[str] = field(default_factory=list)
    tests: List[str] = field(default_factory=list)      # fnmatch on "syrax.test_x::test_name"
    quality_cases: List[str] = field(default_factory=list)
    live: List[str] = field(default_factory=list)        # keys understood by live_checks()
    needs_human: bool = False
    note: str = ""


CAPABILITIES: List[Capability] = [
    Capability("startup", "Startup (launcher, core, UI)", CURRENT, "syrax.py, backend/syrax/server.py",
               tests=["syrax.test_bridge::test_hello_and_brain_panel"], live=["process", "health", "ui"]),
    Capability("routing", "LLM provider routing and failover", CURRENT, "backend/syrax/brains.py, routing.py",
               tests=["syrax.test_brains::test_first_healthy_provider_answers", "syrax.test_brains::test_failover_on_rate_limit_then_cooldown", "syrax.test_routing::*"],
               live=["brains_answered"], note="only providers with a journaled answer count; Pollinations and Ollama have none"),
    Capability("agent", "Agent execution (task to final answer)", CURRENT, "backend/syrax/core.py, agent.py",
               tests=["syrax.test_bridge::test_tool_flow_streams_and_terminates", "syrax.test_bridge::test_chat_task_is_journaled_as_success_with_final_evidence"],
               quality_cases=["arith", "act_concise"], live=["tasks_recent"]),
    Capability("filesystem", "Filesystem access (view, create, edit, delete)", CURRENT, "backend/syrax/editor.py (SyraxEditor)",
               tools=["str_replace_editor"], tests=["syrax.test_editor::*", "syrax.test_editor_view::*"],
               quality_cases=["file_create", "file_edit", "act_not_promise", "act_delete"]),
    Capability("python", "Shell / code execution (python_execute)", CURRENT, "backend/syrax/tools.py (AsyncPythonExecute) + guard.py",
               tools=["python_execute"], tests=["syrax.test_bridge::test_python_execute_does_not_block_loop", "syrax.test_guard::*", "syrax.test_host_guard::*"],
               quality_cases=["python", "act_measure"]),
    Capability("browser", "Browser automation (browser-use MCP)", CURRENT, "backend/syrax/browser.py, app/tool/mcp.py",
               tools=["browser_exec", "browser_screenshot"], tests=["syrax.test_bridge::test_hello_and_brain_panel"],
               note="MCP server connected at boot; failures are page-side JavaScript evaluations"),
    Capability("screenshot", "Screenshot (desktop and browser)", CURRENT, "backend/syrax/desktop.py (_do_screenshot), browser_screenshot",
               tools=["browser_screenshot"], tests=["syrax.test_desktop::test_system_info_and_find_files"], live=["desktop_screenshot"]),
    Capability("desktop", "Desktop automation (apps, media, clipboard, windows)", CURRENT, "backend/syrax/desktop.py, winctl.py",
               tools=["desktop"], tests=["syrax.test_desktop::*"], quality_cases=["desktop_cpu"]),
    Capability("memory", "Memory (remember / recall / forget)", PARTIAL, "backend/syrax/memory.py",
               tools=["remember", "recall", "forget"], tests=["syrax.test_memory::*"],
               note="keyword store, no fact/observation/inference typing; rarely used by the model"),
    Capability("knowledge", "Research and knowledge (research / know / learn)", CURRENT, "backend/syrax/research.py, consolidate.py",
               tools=["research", "know", "learn"], tests=["syrax.test_research::*", "syrax.test_consolidate::*"],
               quality_cases=["know_honest", "research_cite"]),
    Capability("journal", "Durable journal (WAL, owner lock, retention)", CURRENT, "backend/syrax/journal.py",
               tests=["syrax.test_journal::test_open_sets_wal_full_sync_and_private_mode", "syrax.test_journal::test_sigkill_keeps_exactly_the_committed_state",
                      "syrax.test_journal::test_a_second_live_process_cannot_recover_the_journal"], live=["journal_wal"]),
    Capability("persistence", "Task persistence (checkpoints, context)", CURRENT, "backend/syrax/core.py (_checkpoint), journal.py",
               tests=["syrax.test_bridge::test_tool_task_records_steps_operation_and_checkpoints", "syrax.test_journal::test_checkpoint_row_and_event_are_atomic_and_bound"],
               live=["checkpoints"]),
    Capability("cancel", "Task cancellation", CURRENT, "backend/syrax/core.py (cancel), server.py",
               tests=["syrax.test_bridge::test_stop_journals_cancelled", "syrax.test_stop_source::*"], live=["cancelled_tasks"],
               note="not exercised live during the audit (it would create a task)"),
    Capability("recovery", "Recovery / resume after a crash", PARTIAL, "backend/syrax/journal.py (recover_interrupted), core.py (resume)",
               tests=["syrax.test_journal::test_recovery_*", "syrax.test_bridge::test_resume_continues_interrupted_task_with_restored_context"],
               live=["recoveries"], note="only str_replace_editor operations are verified against reality; others stay UNCERTAIN for a human"),
    Capability("frontend", "Frontend (orb, console, panels)", CURRENT, "frontend/components/*.tsx",
               tests=["syrax.test_bridge::test_rejects_foreign_origin"], live=["ui", "gate_frontend"], note="one frontend unit test file (wake words)"),
    Capability("websocket", "WebSocket / HTTP API", CURRENT, "backend/syrax/server.py",
               tests=["syrax.test_bridge::test_hello_and_brain_panel", "syrax.test_bridge::test_task_survives_disconnect_and_reconnect_replays_it"], live=["ws_hello", "health"]),
    Capability("voice_in", "Voice input (server STT)", PARTIAL, "backend/syrax/voice.py (/stt), frontend/lib/mic.ts",
               tests=["syrax.test_voice::test_stt_local_whisper_on_real_speech"], live=["stt_roundtrip"],
               note="server transcription proven by a TTS->STT round trip; microphone capture needs a human"),
    Capability("mic", "Voice input (microphone and wake word)", PARTIAL, "frontend/lib/mic.ts, wake.ts, useHandsFree.ts",
               needs_human=True, note="cannot be exercised without a person at the microphone"),
    Capability("voice_out", "Voice output (TTS)", CURRENT, "backend/syrax/voice.py (/tts, edge-tts)",
               tests=["syrax.test_voice::test_tts_endpoint"], live=["tts"]),
    Capability("gate", "Verification / release gate", CURRENT, "backend/syrax/verify.py",
               tests=["syrax.test_verify::*"], live=["gate"]),
    Capability("selfmodel", "Self-model (identity, capabilities, weaknesses)", CURRENT, "backend/syrax/selfmodel.py",
               tools=["self_inspect"], tests=["syrax.test_selfmodel::*", "syrax.test_utf8_reads::*"], quality_cases=["self_version"], live=["self_model"]),
    Capability("autonomy", "Self-improvement loop (objectives, judge, follow-ups)", CURRENT, "backend/syrax/autonomy.py, limits.py, plan.py, followup.py",
               tests=["syrax.test_autonomy::*", "syrax.test_limits::*", "syrax.test_plan::*", "syrax.test_followup::*"], live=["cycles"]),
    Capability("release", "Autonomous self-modification (release, review, rollback)", PARTIAL, "backend/syrax/devloop.py, review.py",
               tools=["release"], tests=["syrax.test_devloop::*"],
               note="gate + rollback + cross-brain review exist; SYRAX has never landed its own commit; edits land in the live tree"),
    Capability("skills", "Skill / tool creation (skill_create, tests, registry)", CURRENT, "backend/syrax/skills.py, skillevo.py",
               tools=["skill_create", "skill_test", "make_docx", "make_xlsx", "make_pptx", "make_pdf"],
               tests=["syrax.test_skills::*", "syrax.test_skill_safety::*", "syrax.test_skillevo::*"], live=["skills_verified"]),
    Capability("presentation", "Presentation engine (stage elements)", PARTIAL, "backend/syrax/presentation.py, frontend/components/Stage.tsx",
               tools=["present"], tests=["syrax.test_presentation::*"], quality_cases=["present_table"],
               note="stage only; elements are not restored after a restart"),
    Capability("permissions", "Tool permission levels enforced in code", CURRENT, "syrax/permissions.py, agent._permit",
               tests=["syrax.test_permissions*::*"], quality_cases=["act_delete"], live=["permissions"],
               note="READ_ONLY..DESTRUCTIVE + harm; conversation authorizes by goal or consent, eval never asks, autonomous refuses SYSTEM and above (improvement 001)"),
    Capability("phases", "Task phase model (understand/plan/act/observe/verify)", MISSING, "(none)",
               note="only a free-text stage column exists"),
    Capability("presence", "Visible Work Presence (visibility, hide/show, timeline)", PLANNED, "(none)",
               note="specified 2026-10-03, not built"),
]


# ——— evidence loaders ———

def read_journal(path: Path, now: Optional[float] = None) -> Dict[str, Any]:
    now = now or time.time()
    c = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    try:
        out: Dict[str, Any] = {"tool_stats": tool_stats(c, now)}
        # per case, the latest verdict within the window: a later subset run must
        # not hide a case that failed in the last full run and was not re-run since
        cases: Dict[str, bool] = {}
        runs: Dict[str, int] = {}
        latest = None
        for qr in c.execute("SELECT id, ts, pass_rate, status, results FROM quality_runs WHERE ts>? ORDER BY id DESC", (now - WINDOW_DAYS * 86400,)):
            latest = latest or qr
            for r in json.loads(qr["results"] or "[]"):
                if r.get("id") and r["id"] not in cases:
                    cases[r["id"]] = bool(r.get("ok"))
                    runs[r["id"]] = qr["id"]
        out["quality"] = {"id": latest["id"], "ts": latest["ts"], "pass_rate": latest["pass_rate"], "status": latest["status"],
                          "cases": cases, "runs": runs} if latest else None
        vr = c.execute("SELECT id, ts, status, git_head FROM verifications ORDER BY id DESC LIMIT 1").fetchone()
        out["verification"] = dict(vr) if vr else None
        out["skills_verified"] = [r["name"] for r in c.execute("SELECT name FROM skills WHERE status='VERIFIED' ORDER BY name")]
        out["counts"] = {
            "tasks_recent": c.execute("SELECT COUNT(*) FROM tasks WHERE status='SUCCESS' AND created>?", (now - WINDOW_DAYS * 86400,)).fetchone()[0],
            "checkpoints": c.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0],
            "cancelled_tasks": c.execute("SELECT COUNT(*) FROM tasks WHERE status='CANCELLED'").fetchone()[0],
            "recoveries": c.execute("SELECT COUNT(*) FROM events WHERE type='recovery.completed'").fetchone()[0],
            "cycles": c.execute("SELECT COUNT(*) FROM events WHERE type='cycle.completed' AND ts>?", (now - WINDOW_DAYS * 86400,)).fetchone()[0],
            "permission_authorized": c.execute("SELECT COUNT(*) FROM events WHERE type='permission.authorized' AND ts>?", (now - WINDOW_DAYS * 86400,)).fetchone()[0],
            "permission_refused": c.execute("SELECT COUNT(*) FROM events WHERE type='permission.refused' AND ts>?", (now - WINDOW_DAYS * 86400,)).fetchone()[0],
            "brains_answered": c.execute("SELECT COUNT(DISTINCT json_extract(payload,'$.provider')) FROM events WHERE type='brain.answered' AND ts>?", (now - WINDOW_DAYS * 86400,)).fetchone()[0],
            "desktop_screenshot": c.execute("SELECT COUNT(*) FROM events WHERE type='tool.completed' AND json_extract(payload,'$.name')='desktop' AND id IN "
                                            "(SELECT e2.id FROM events e2 JOIN events e1 ON e1.task_id=e2.task_id AND json_extract(e1.payload,'$.id')=json_extract(e2.payload,'$.id') "
                                            "WHERE e1.type='tool.started' AND json_extract(e1.payload,'$.args.action')='screenshot')").fetchone()[0],
        }
        out["journal_wal"] = c.execute("PRAGMA journal_mode").fetchone()[0]
        return out
    finally:
        c.close()


def tool_stats(c: sqlite3.Connection, now: float) -> Dict[str, dict]:
    """Same counting as Journal.tool_stats (uses from tool.started), plus a
    WINDOW_DAYS window."""
    since = now - WINDOW_DAYS * 86400
    out: Dict[str, dict] = {}
    for r in c.execute("SELECT type, ts, json_extract(payload,'$.name') AS name FROM events WHERE type IN ('tool.started','tool.completed','tool.failed') AND name IS NOT NULL ORDER BY id"):
        st = out.setdefault(r["name"], {"uses": 0, "successes": 0, "failures": 0, "last_used": None, "last_failed": None, "last_outcome": None,
                                        "recent_ok": 0, "recent_fail": 0, "last_ok": None})
        if r["type"] == "tool.started":
            st["uses"] += 1
            st["last_used"] = r["ts"]
        elif r["type"] == "tool.completed":
            st["successes"] += 1
            st["last_outcome"] = "ok"
            st["last_ok"] = r["ts"]
            if r["ts"] >= since:
                st["recent_ok"] += 1
        else:
            st["failures"] += 1
            st["last_failed"] = r["ts"]
            st["last_outcome"] = "fail"
            if r["ts"] >= since:
                st["recent_fail"] += 1
    return out


def read_junit(path: Optional[Path]) -> Dict[str, str]:
    """{"syrax.test_x::test_name": "pass"|"fail"|"skip"}"""
    if not path or not Path(path).exists():
        return {}
    root = ET.parse(path).getroot()
    out = {}
    for tc in root.iter("testcase"):
        key = f"{tc.get('classname')}::{tc.get('name')}"
        if tc.find("failure") is not None or tc.find("error") is not None:
            out[key] = "fail"
        elif tc.find("skipped") is not None:
            out[key] = "skip"
        else:
            out[key] = "pass"
    return out


def junit_totals(path: Optional[Path]) -> Optional[dict]:
    if not path or not Path(path).exists():
        return None
    root = ET.parse(path).getroot()
    s = root if root.tag == "testsuite" else root.find("testsuite")
    a = s.attrib
    t, f, e, k = int(a.get("tests", 0)), int(a.get("failures", 0)), int(a.get("errors", 0)), int(a.get("skipped", 0))
    return {"tests": t, "passed": t - f - e - k, "failed": f, "errors": e, "skipped": k, "seconds": round(float(a.get("time", 0)), 1)}


def read_gate(path: Optional[Path]) -> Optional[dict]:
    if not path or not Path(path).exists():
        return None
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    m = re.search(r"VERIFICATION (GREEN|BLOCKED)", text)
    gates = {name: st for st, name in re.findall(r"^\s+(PASS|FAIL|NOT_VERIFIED)\s+(\w+)", text, re.M)}
    return {"status": m.group(1) if m else None, "gates": gates}


def live_checks(evidence: Optional[dict], gate: Optional[dict], journal: Dict[str, Any]) -> Dict[str, tuple]:
    """key -> (result, detail) with result in pass | fail | blocked | None (no evidence)."""
    ev = evidence or {}
    http, ws, voice, proc = ev.get("http") or {}, ev.get("ws") or {}, ev.get("voice") or {}, ev.get("process") or {}
    out: Dict[str, tuple] = {}
    health = (http.get("health") or {}).get("json") or {}
    out["health"] = ("pass", f"/health {health.get('status')}") if health.get("status") == "online" else (("fail", "no /health") if http else (None, ""))
    ui = ev.get("ui") or {}
    out["ui"] = ("pass", f"UI {ui.get('status')} '{ui.get('title')}'") if ui.get("status") == 200 else (("fail", f"UI {ui.get('status')}") if ui else (None, ""))
    out["process"] = ("pass", f"pid {proc.get('pid')} alive") if proc.get("pid_alive") else (("fail", "pid not alive") if proc else (None, ""))
    tools = (ws.get("hello") or {}).get("tools") or []
    out["ws_hello"] = ("pass", f"hello with {len(tools)} tools") if tools else (("fail", ws.get("error", "no hello")) if ws else (None, ""))
    tts = voice.get("tts") or {}
    if tts:
        out["tts"] = ("pass", f"{tts.get('bytes')} B in {tts.get('ms')} ms") if tts.get("status") == 200 and (tts.get("bytes") or 0) > 0 else \
            (("blocked", f"TTS {tts.get('error') or tts.get('status')} (network)") if "502" in str(tts.get("error", "")) or "503" in str(tts.get("error", "")) else ("fail", str(tts.get("error") or tts.get("status"))))
    else:
        out["tts"] = (None, "")
    if "roundtrip_pass" in voice:
        stt = (voice.get("stt") or {}).get("json") or {}
        out["stt_roundtrip"] = ("pass" if voice["roundtrip_pass"] else "fail", f"{stt.get('engine')} heard {str(stt.get('text'))[:60]!r}")
    else:
        out["stt_roundtrip"] = (None, "")
    moj = (http.get("self_structure") or {}).get("mojibake_count")
    out["self_model"] = (None, "") if moj is None else (("pass", "no mojibake in /self") if moj == 0 else ("fail", f"{moj} mojibake in /self?section=structure"))
    if gate:
        req = {k: v for k, v in gate["gates"].items() if k != "performance"}
        ok = gate["status"] == "GREEN"
        out["gate"] = ("pass" if ok else "fail", f"gate {gate['status']}: " + ", ".join(f"{k} {v}" for k, v in gate["gates"].items()))
        fe = {k: req.get(k) for k in ("tsc", "eslint", "node_test", "next_build")}
        out["gate_frontend"] = ("pass" if all(v == "PASS" for v in fe.values()) else "fail", "frontend gates " + ", ".join(f"{k} {v}" for k, v in fe.items()))
    else:
        out["gate"] = out["gate_frontend"] = (None, "")
    counts = journal.get("counts") or {}
    for key, label in (("tasks_recent", "SUCCESS tasks"), ("checkpoints", "checkpoints"), ("cancelled_tasks", "cancelled tasks"),
                       ("recoveries", "recoveries"), ("cycles", "cycles"), ("brains_answered", "providers answered"), ("desktop_screenshot", "desktop screenshots")):
        n = counts.get(key, 0)
        out[key] = ("pass", f"{n} {label}" + (f" in {WINDOW_DAYS} d" if key in ("tasks_recent", "cycles", "brains_answered") else "")) if n else (None, f"0 {label}")
    pa, pr = counts.get("permission_authorized", 0), counts.get("permission_refused", 0)
    # the gate is proven at runtime only when it has both let a named action through and refused one
    out["permissions"] = ("pass" if pa and pr else None, f"{pa} authorized / {pr} refused decisions in {WINDOW_DAYS} d")
    out["journal_wal"] = ("pass", f"journal_mode={journal.get('journal_wal')}") if journal.get("journal_wal") == "wal" else ("fail", f"journal_mode={journal.get('journal_wal')}")
    sk = journal.get("skills_verified") or []
    out["skills_verified"] = ("pass", f"{len(sk)} VERIFIED skills: {', '.join(sk)}") if sk else (None, "no VERIFIED skill")
    return out


# ——— the rules ———

def evaluate(cap: Capability, journal: Dict[str, Any], tests: Dict[str, str], live: Dict[str, tuple], now: Optional[float] = None) -> dict:
    now = now or time.time()
    since = now - WINDOW_DAYS * 86400
    matched = {k: v for k, v in tests.items() if any(fnmatch.fnmatch(k, p) for p in cap.tests)}
    failed_tests = sorted(k for k, v in matched.items() if v == "fail")
    passed_tests = sum(1 for v in matched.values() if v == "pass")
    q = journal.get("quality") or {}
    qcases = {c: q.get("cases", {}).get(c) for c in cap.quality_cases}
    qfail = sorted(c for c, ok in qcases.items() if ok is False)
    qpass = sorted(c for c, ok in qcases.items() if ok is True)
    lv = {k: live.get(k, (None, "")) for k in cap.live}
    lfail = [k for k, (r, _) in lv.items() if r == "fail"]
    lblocked = [k for k, (r, _) in lv.items() if r == "blocked"]
    lpass = [k for k, (r, _) in lv.items() if r == "pass"]
    ts = journal.get("tool_stats") or {}
    rec_ok = sum(ts.get(t, {}).get("recent_ok", 0) for t in cap.tools)
    rec_fail = sum(ts.get(t, {}).get("recent_fail", 0) for t in cap.tools)
    all_ok = sum(ts.get(t, {}).get("successes", 0) for t in cap.tools)
    all_fail = sum(ts.get(t, {}).get("failures", 0) for t in cap.tools)
    last_ok = max((ts.get(t, {}).get("last_ok") or 0 for t in cap.tools), default=0)
    share = round(rec_fail / (rec_ok + rec_fail), 2) if (rec_ok + rec_fail) else None

    evidence = []
    if matched:
        evidence.append(f"tests {passed_tests}/{len(matched)} pass")
    if cap.tools:
        evidence.append(f"journal tool.*: {all_ok} ok / {all_fail} fail all-time; last {WINDOW_DAYS} d {rec_ok} ok / {rec_fail} fail")
    if cap.quality_cases and q:
        runs = q.get("runs") or {}
        evidence.append("quality: " + ", ".join(f"{c} {'pass' if ok else 'FAIL' if ok is False else 'n/a'}" + (f" (#{runs[c]})" if c in runs else "") for c, ok in qcases.items()))
    for k, (r, d) in lv.items():
        if r:
            evidence.append(f"live {k}: {r} ({d})")

    runtime_ok = bool(lpass) or bool(qpass) or (last_ok and last_ok >= since)
    if cap.implementation == MISSING:
        status, why = RED, "not implemented"
    elif cap.implementation == PLANNED:
        status, why = UNVERIFIED, "planned, not built"
    elif failed_tests or qfail or lfail:
        status, why = RED, "; ".join(filter(None, [f"failing tests: {', '.join(failed_tests[:3])}" if failed_tests else "",
                                                     f"quality case failed: {', '.join(qfail)}" if qfail else "",
                                                     f"live check failed: {', '.join(lfail)}" if lfail else ""]))
    elif lblocked:
        status, why = BLOCKED, "external cause: " + "; ".join(lv[k][1] for k in lblocked)
    elif cap.needs_human:
        status, why = UNVERIFIED, "needs a human at the machine"
    elif not passed_tests or not runtime_ok:
        status, why = UNVERIFIED, "no passing test mapped" if not passed_tests else f"no runtime success within {WINDOW_DAYS} d"
    elif cap.implementation == CURRENT and (share is None or share <= MAX_FAIL):
        status, why = GREEN, "tests pass, recent runtime evidence" + (f", failure share {share:.0%}" if share is not None else "")
    else:
        status, why = YELLOW, (f"failure share {share:.0%} > {MAX_FAIL:.0%}" if share is not None and share > MAX_FAIL else f"implementation {cap.implementation}")
    runtime = ", ".join(filter(None, [", ".join(f"quality:{c}" for c in cap.quality_cases), ", ".join(f"live:{k}" for k in cap.live)])) or "—"
    return {"id": cap.id, "label": cap.label, "implementation": f"{cap.implementation} ({cap.where})", "runtime_test": runtime,
            "verification": f"tests {passed_tests}/{len(matched)}" if matched else "no test mapped", "evidence": "; ".join(evidence) or "none",
            "status": status, "why": why, "note": cap.note}


def render(rows: List[dict], head: str, journal_path: str, totals: Optional[dict], coverage: Optional[dict], generated: Optional[str] = None) -> str:
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in ORDER}
    lines = ["# SYRAX capability matrix", "",
             f"Generated {generated or time.strftime('%Y-%m-%d %H:%M %z')} by `python -m syrax.capmatrix` from commit `{head}`, journal `{journal_path}`, "
             f"evidence window {WINDOW_DAYS} days, max failure share {MAX_FAIL:.0%}. Status is computed, not typed: "
             "GREEN needs passing mapped tests **and** runtime evidence within the window; RED is a failing test, quality case or live check; "
             "BLOCKED is an external cause; UNVERIFIED is missing evidence or a planned capability.", ""]
    if totals:
        lines.append(f"Test suite: {totals['passed']} passed, {totals['failed']} failed, {totals['errors']} errors, {totals['skipped']} skipped of {totals['tests']} in {totals['seconds']} s.")
        lines.append("")
    lines += ["| Capability | Implementation | Runtime Test | Verification | Evidence | Status |", "|---|---|---|---|---|---|"]
    for r in rows:
        note = f" _{r['note']}_" if r["note"] else ""
        lines.append(f"| {r['label']} | {r['implementation']} | {r['runtime_test']} | {r['verification']} | {r['evidence']}{note} | **{r['status']}** — {r['why']} |")
    lines += ["", "## Totals", "", " · ".join(f"{s} {counts[s]}" for s in ORDER) + f" · total {len(rows)}", ""]
    for s in ORDER:
        names = [r["label"] for r in rows if r["status"] == s]
        if names:
            lines.append(f"- **{s}**: " + "; ".join(names))
    if coverage:
        lines += ["", "## System map coverage", "",
                  f"{coverage['referenced']}/{coverage['modules']} modules in `backend/syrax` are referenced by `docs/system_map.json`"
                  + (f"; missing: {', '.join(coverage['missing'])}" if coverage["missing"] else "") + "."]
    return "\n".join(lines) + "\n"


def map_coverage(repo: Path = REPO_ROOT) -> dict:
    m = json.loads((repo / "docs" / "system_map.json").read_text(encoding="utf-8"))
    refd = {Path(str(code).split(" ")[0]).stem for comp in m["components"] for code in comp.get("code") or [] if str(code).startswith("backend/syrax/")}
    mods = sorted(p.stem for p in (repo / "backend" / "syrax").glob("*.py") if not p.stem.startswith("test_") and p.stem not in ("__init__", "conftest"))
    missing = [x for x in mods if x not in refd]
    return {"modules": len(mods), "referenced": len(mods) - len(missing), "missing": missing, "components": [c["component"] for c in m["components"]]}


def build(journal_path: Path, junit: Optional[Path] = None, evidence: Optional[Path] = None, gate: Optional[Path] = None,
          head: str = "?", repo: Path = REPO_ROOT, now: Optional[float] = None) -> tuple:
    journal = read_journal(journal_path, now)
    tests = read_junit(junit)
    ev = json.loads(Path(evidence).read_text(encoding="utf-8")) if evidence and Path(evidence).exists() else None
    live = live_checks(ev, read_gate(gate), journal)
    rows = [evaluate(c, journal, tests, live, now) for c in CAPABILITIES]
    return rows, render(rows, head, str(journal_path), junit_totals(junit), map_coverage(repo))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--journal", default=str(DEFAULT_FILE))
    ap.add_argument("--junit")
    ap.add_argument("--evidence")
    ap.add_argument("--gate")
    ap.add_argument("--head")
    ap.add_argument("--out", default=str(REPO_ROOT / "docs" / "CAPABILITY_MATRIX.md"))
    a = ap.parse_args(argv)
    head = a.head
    if not head:
        import subprocess
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(REPO_ROOT), capture_output=True, text=True, encoding="utf-8").stdout.strip() or "?"
    rows, text = build(Path(a.journal), Path(a.junit) if a.junit else None, Path(a.evidence) if a.evidence else None, Path(a.gate) if a.gate else None, head)
    Path(a.out).write_text(text, encoding="utf-8")
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in ORDER}
    print(f"{a.out}: " + " ".join(f"{s}={n}" for s, n in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
