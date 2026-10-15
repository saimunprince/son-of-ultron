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

from syrax.journal import BACKEND_ROOT, DEFAULT_FILE, misuse

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
               tools=["browser_exec", "browser_screenshot"], tests=["syrax.test_bridge::test_hello_and_brain_panel", "syrax.test_quality_browser::*"],
               quality_cases=["browser_read"],
               note="MCP server connected at boot; failures are page-side JavaScript evaluations"),
    Capability("screenshot", "Screenshot (desktop and browser)", CURRENT, "backend/syrax/desktop.py (_do_screenshot), browser_screenshot",
               tools=["browser_screenshot"], tests=["syrax.test_desktop::test_system_info_and_find_files"], live=["desktop_screenshot"]),
    Capability("desktop", "Desktop automation (apps, media, clipboard, windows)", CURRENT, "backend/syrax/desktop.py, winctl.py",
               tools=["desktop"], tests=["syrax.test_desktop::*"], quality_cases=["desktop_cpu"]),
    Capability("memory", "Memory (remember / recall / forget)", CURRENT, "backend/syrax/memory.py",
               tools=["remember", "recall", "forget"], tests=["syrax.test_memory::*", "syrax.test_memory_types::*"],
               note="typed: fact / preference / rule from the human, observation (SYRAX's inference, half the weight) kept apart; "
                    "keyword recall, no embeddings"),
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
               live=["recoveries"], note="edits are checked against the files and calls that only read resume safely; code, browser and writing calls stay UNCERTAIN, listed with their level and targets for a human"),
    Capability("frontend", "Frontend (orb, console, panels)", CURRENT, "frontend/components/*.tsx",
               tests=["syrax.test_bridge::test_rejects_foreign_origin"], live=["ui", "gate_frontend"], note="one frontend unit test file (wake words)"),
    Capability("websocket", "WebSocket / HTTP API", CURRENT, "backend/syrax/server.py",
               tests=["syrax.test_bridge::test_hello_and_brain_panel", "syrax.test_bridge::test_task_survives_disconnect_and_reconnect_replays_it"], live=["ws_hello", "health"]),
    Capability("voice_in", "Voice input (server STT)", PARTIAL, "backend/syrax/voice.py (/stt), frontend/lib/mic.ts",
               tests=["syrax.test_voice::test_stt_*"], live=["stt_roundtrip"],
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
               note="gate + rollback + cross-brain review; the landing rate is in RISE.md (Releases that landed)"),
    Capability("isolation", "Isolated evolution (own changes in a worktree, fast-forward landing)", CURRENT,
               "backend/syrax/devloop.py (isolate, land), editor.py (redirect), guard.py (isolation rules)",
               tests=["syrax.test_isolated_evolution::*", "syrax.test_isolated_redirect::*", "syrax.test_guard_isolation::*", "syrax.test_m1_gaps::*"],
               live=["isolated_commits"], note="M1; the running tree changes only by a fast-forward of a gated, reviewed commit"),
    Capability("ledger", "Self-published evidence (RISE ledger and this matrix)", CURRENT,
               "backend/syrax/rise.py, ledger.py, capmatrix.py, probe.py",
               tests=["syrax.test_ledger_publish::*", "syrax.test_rise::*", "syrax.test_capmatrix::*", "syrax.test_matrix_publish::*"],
               live=["ledger_published"], note="M3; regenerated daily from the journal, the test suite and live probes, released like any own change"),
    Capability("codebench", "Code-change benchmark per brain", CURRENT, "backend/syrax/codebench.py, routing.py (preferred_for_code)",
               tests=["syrax.test_codebench::*"], live=["codebench_runs"],
               note="M2; release objectives start on the brain that finishes code changes best"),
    Capability("skills", "Skill / tool creation (skill_create, tests, registry)", CURRENT, "backend/syrax/skills.py, skillevo.py",
               tools=["skill_create", "skill_test", "make_docx", "make_xlsx", "make_pptx", "make_pdf"],
               tests=["syrax.test_skills::*", "syrax.test_skill_safety::*", "syrax.test_skillevo::*"], live=["skills_verified"]),
    Capability("presentation", "Presentation engine (stage elements)", CURRENT, "backend/syrax/presentation.py, frontend/components/Stage.tsx",
               tools=["present"], tests=["syrax.test_presentation::*", "syrax.test_presentation_restore::*"], quality_cases=["present_table"],
               note="stage only; restored from the journal after a restart (a day, not dismissed, within ttl)"),
    Capability("permissions", "Tool permission levels enforced in code", CURRENT, "syrax/permissions.py, agent._permit",
               tests=["syrax.test_permissions*::*"], quality_cases=["act_delete"], live=["permissions"],
               note="READ_ONLY..DESTRUCTIVE + harm; conversation authorizes by goal or consent, eval never asks, autonomous refuses SYSTEM and above (improvement 001)"),
    Capability("phases", "Task phase model (understand/plan/act/observe/verify)", CURRENT,
               "backend/syrax/phases.py, core.py (_record_phase), frontend/components/Syrax.tsx (phase strip)",
               tests=["syrax.test_phases::*"], live=["phases"],
               note="F4; the phase is a pure function of the journaled events, never stored (test_bridge pins task event sequences)"),
    Capability("live_voice", "Live talk (real-time voice through Gemini Live)", CURRENT, "backend/syrax/live.py (/live), frontend/lib/live.ts",
               tests=["syrax.test_live::*"], live=["live_sessions"],
               note="the microphone streams to Google only while TALK is on; tasks go through the agent and its permissions"),
    Capability("sight", "Click what it sees (UI Automation, then OCR)", CURRENT, "backend/syrax/sight.py, sight.ps1, desktop.py (click_text, find_text)",
               tests=["syrax.test_sight::*"], live=["sight_used"],
               note="primary screen only; a tie clicks nothing and lists the candidates"),
    Capability("presence", "Visible Work Presence (visibility, hide/show, timeline)", PARTIAL,
               "backend/syrax/presence.py, server.py (presence, hello), hud/ (link.js, main.js: visible / minimal / hidden)",
               tests=["syrax.test_presence::*", "syrax.test_hud::*"],
               note="Level 1-2 on the HUD (task, phase, tool, target window, log from the journal) and the three levels by text "
                    "or voice; the target window is observed only right after a desktop or browser call, private titles never recorded; "
                    "Level 3 (live workspace) is the owner's decision"),
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
        green = c.execute("SELECT id, ts FROM verifications WHERE status='GREEN' ORDER BY id DESC LIMIT 1").fetchone()
        out["last_green_verification"] = dict(green) if green else None
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
            "isolated_commits": c.execute("SELECT COUNT(*) FROM events e WHERE e.type='commit.created' AND e.ts>? AND e.task_id IN "
                                          "(SELECT task_id FROM events WHERE type='isolation.started')", (now - WINDOW_DAYS * 86400,)).fetchone()[0],
            "ledger_published": c.execute("SELECT COUNT(*) FROM tasks WHERE status='SUCCESS' AND goal LIKE '[MAINTENANCE] publish the rise ledger%' AND created>?",
                                          (now - WINDOW_DAYS * 86400,)).fetchone()[0],
            "codebench_runs": c.execute("SELECT COUNT(*) FROM events WHERE type='codebench.completed' AND json_extract(payload,'$.graded')>0 AND ts>?",
                                        (now - WINDOW_DAYS * 86400,)).fetchone()[0],
            "live_sessions": c.execute("SELECT COUNT(*) FROM events WHERE type='live.closed' AND ts>?", (now - WINDOW_DAYS * 86400,)).fetchone()[0],
            "sight_used": c.execute("SELECT COUNT(*) FROM events WHERE type='tool.completed' AND json_extract(payload,'$.name')='desktop' AND ts>? AND id IN "
                                    "(SELECT e2.id FROM events e2 JOIN events e1 ON e1.task_id=e2.task_id AND json_extract(e1.payload,'$.id')=json_extract(e2.payload,'$.id') "
                                    "WHERE e1.type='tool.started' AND json_extract(e1.payload,'$.args.action') IN ('click_text','find_text'))",
                                    (now - WINDOW_DAYS * 86400,)).fetchone()[0],
            "desktop_screenshot": c.execute("SELECT COUNT(*) FROM events WHERE type='tool.completed' AND json_extract(payload,'$.name')='desktop' AND id IN "
                                            "(SELECT e2.id FROM events e2 JOIN events e1 ON e1.task_id=e2.task_id AND json_extract(e1.payload,'$.id')=json_extract(e2.payload,'$.id') "
                                            "WHERE e1.type='tool.started' AND json_extract(e1.payload,'$.args.action')='screenshot')").fetchone()[0],
        }
        out["journal_wal"] = c.execute("PRAGMA journal_mode").fetchone()[0]
        out["phases"] = phase_evidence(c, now)
        return out
    finally:
        c.close()


def phase_evidence(c: sqlite3.Connection, now: float, last: int = 30) -> Dict[str, int]:
    """How many of the latest SUCCESS tasks in the window reach `verify`, with the
    phases recomputed from their journaled events exactly as the UI does (phases.path)."""
    from syrax import phases

    ids = [r[0] for r in c.execute("SELECT task_id FROM tasks WHERE status='SUCCESS' AND created>? ORDER BY created DESC LIMIT ?",
                                   (now - WINDOW_DAYS * 86400, last))]
    reached = 0
    for tid in ids:
        evs = [{"id": r[0], "type": r[1], "payload": json.loads(r[2] or "{}")}
               for r in c.execute("SELECT id, type, payload FROM events WHERE task_id=? ORDER BY seq", (tid,))]
        reached += [p["phase"] for p in phases.path(evs)][-1:] == ["verify"]
    return {"tasks": len(ids), "verified": reached}


def tool_stats(c: sqlite3.Connection, now: float) -> Dict[str, dict]:
    """Same counting as Journal.tool_stats (uses from tool.started; a call a guard
    refused is no use and no failure), plus a WINDOW_DAYS window."""
    since = now - WINDOW_DAYS * 86400
    out: Dict[str, dict] = {}
    started: Dict[tuple, tuple] = {}
    for r in c.execute("SELECT type, ts, task_id, json_extract(payload,'$.name') AS name, json_extract(payload,'$.id') AS cid, "
                       "json_extract(payload,'$.refused') AS refused, CASE WHEN type='tool.failed' THEN substr(json_extract(payload,'$.output'), 1, 400) END AS output "
                       "FROM events WHERE type IN ('tool.started','tool.completed','tool.failed') "
                       "AND name IS NOT NULL ORDER BY id"):
        st = out.setdefault(r["name"], {"uses": 0, "successes": 0, "failures": 0, "refused": 0, "last_used": None, "last_failed": None,
                                        "last_outcome": None, "recent_ok": 0, "recent_fail": 0, "last_ok": None})
        if r["type"] == "tool.started":
            started[(r["task_id"], r["cid"])] = (st["last_used"], r["ts"])
            st["uses"] += 1
            st["last_used"] = r["ts"]
        elif r["type"] == "tool.failed" and r["refused"]:
            prev, ts = started.pop((r["task_id"], r["cid"]), (st["last_used"], None))
            st["uses"] -= ts is not None
            st["refused"] += 1
            if ts is not None and st["last_used"] == ts:
                st["last_used"] = prev
        elif r["type"] == "tool.completed":
            st["successes"] += 1
            st["last_outcome"] = "ok"
            st["last_ok"] = r["ts"]
            if r["ts"] >= since:
                st["recent_ok"] += 1
        else:
            st["failures"] += 1
            st["last_failed"] = r["ts"]
            st["last_outcome"] = "misuse" if misuse(r["name"], r["output"]) else "fail"
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
    # which tests failed, not only how many: SYRAX's ledger of 2026-10-15 said "1 failed" and its JUnit
    # report went with the maintenance worktree, so nobody could say which test it was
    failing = []
    for tc in root.iter("testcase"):
        bad = tc.find("failure") if tc.find("failure") is not None else tc.find("error")
        if bad is not None:
            msg = " ".join(str(bad.get("message") or bad.text or "").split())[:160]
            failing.append({"test": f"{tc.get('classname')}::{tc.get('name')}", "message": msg})
    return {"tests": t, "passed": t - f - e - k, "failed": f, "errors": e, "skipped": k, "seconds": round(float(a.get("time", 0)), 1),
            "failing": failing[:10]}


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
        # The capability is the gate itself: it ran every required check to a verdict, and it has passed a
        # change within the window. A gate that blocks a failing candidate is doing its job (live 2026-10-15:
        # the row read RED because the last verification blocked SYRAX's own change, which broke a test).
        complete = bool(req) and all(v in ("PASS", "FAIL") for v in req.values())
        green = journal.get("last_green_verification") or {}
        recent_green = gate["status"] == "GREEN" or (bool(green) and green.get("ts", 0) >= time.time() - WINDOW_DAYS * 86400)
        ok = complete and recent_green
        why = (f"gate {gate['status']}: " + ", ".join(f"{k} {v}" for k, v in gate["gates"].items())
               + ("" if ok else (" (a required check did not reach a verdict)" if not complete else f" (no GREEN verification in {WINDOW_DAYS} d)")))
        out["gate"] = ("pass" if ok else "fail", why)
        fe = {k: req.get(k) for k in ("tsc", "eslint", "node_test", "next_build")}
        out["gate_frontend"] = ("pass" if all(v == "PASS" for v in fe.values()) else "fail", "frontend gates " + ", ".join(f"{k} {v}" for k, v in fe.items()))
    else:
        out["gate"] = out["gate_frontend"] = (None, "")
    counts = journal.get("counts") or {}
    for key, label in (("tasks_recent", "SUCCESS tasks"), ("checkpoints", "checkpoints"), ("cancelled_tasks", "cancelled tasks"),
                       ("recoveries", "recoveries"), ("cycles", "cycles"), ("brains_answered", "providers answered"), ("desktop_screenshot", "desktop screenshots"),
                       ("isolated_commits", "own commits landed from a worktree"), ("ledger_published", "self-published ledgers"),
                       ("codebench_runs", "code benchmark runs"), ("live_sessions", "live talk sessions"),
                       ("sight_used", "click_text/find_text uses")):
        n = counts.get(key, 0)
        windowed = ("tasks_recent", "cycles", "brains_answered", "isolated_commits", "ledger_published", "codebench_runs",
                    "live_sessions", "sight_used")
        out[key] = ("pass", f"{n} {label}" + (f" in {WINDOW_DAYS} d" if key in windowed else "")) if n else (None, f"0 {label}")
    pa, pr = counts.get("permission_authorized", 0), counts.get("permission_refused", 0)
    # the gate is proven at runtime only when it has both let a named action through and refused one
    out["permissions"] = ("pass" if pa and pr else None, f"{pa} authorized / {pr} refused decisions in {WINDOW_DAYS} d")
    out["journal_wal"] = ("pass", f"journal_mode={journal.get('journal_wal')}") if journal.get("journal_wal") == "wal" else ("fail", f"journal_mode={journal.get('journal_wal')}")
    ph = journal.get("phases") or {}
    out["phases"] = (("pass" if ph.get("verified") else None),
                     f"{ph.get('verified', 0)} of the last {ph.get('tasks', 0)} SUCCESS tasks reached verify (phases from their events)")
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
        for x in totals.get("failing") or []:
            lines.append(f"- failing: `{x['test']}`" + (f" ({x['message'].replace('|', '/')})" if x["message"] else ""))
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


def gate_from_verification(v: Optional[dict]) -> Optional[dict]:
    """A journaled verification (Journal.verifications) in read_gate's shape."""
    if not v:
        return None
    return {"status": v.get("status"), "gates": {g.get("name"): g.get("status") for g in v.get("gates") or [] if g.get("name")}}


def build(journal_path: Path, junit: Optional[Path] = None, evidence: Optional[Path] = None, gate: Optional[Path] = None,
          head: str = "?", repo: Path = REPO_ROOT, now: Optional[float] = None, evidence_data: Optional[dict] = None,
          gate_data: Optional[dict] = None, journal_label: Optional[str] = None) -> tuple:
    """Rows and the rendered matrix. Evidence and the gate come from files (the CLI)
    or in memory (the daily publish: syrax.probe and the journal's last verification)."""
    journal = read_journal(journal_path, now)
    tests = read_junit(junit)
    ev = evidence_data if evidence_data is not None else (
        json.loads(Path(evidence).read_text(encoding="utf-8")) if evidence and Path(evidence).exists() else None)
    live = live_checks(ev, gate_data if gate_data is not None else read_gate(gate), journal)
    rows = [evaluate(c, journal, tests, live, now) for c in CAPABILITIES]
    return rows, render(rows, head, journal_label or str(journal_path), junit_totals(junit), map_coverage(repo))


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
