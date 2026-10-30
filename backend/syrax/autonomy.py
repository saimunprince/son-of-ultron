"""SYRAX autonomy: objectives and the bounded self-directed cycle.

    Cycle
      check system (resource gate)
      derive objectives from the self-model's weaknesses (idempotent)
      pick the highest-priority OPEN objective whose dependencies are DONE
      run ONE autonomous task for it through the core (same agent, same tools)
      judge the outcome from JOURNAL EVIDENCE, never from the model's words
      reflect: record what was expected, what happened, what was learned
      next objective on the next cycle, or idle

Bounds: autonomy is OFF unless enabled (journal meta ``autonomy_enabled`` or
``SYRAX_AUTONOMY=1``); at most one task per cycle; a minimum interval between
cycles; an objective is BLOCKED after MAX_ATTEMPTS failed attempts; nothing
runs while a human task is running or the machine is under pressure.

Objective checks (machine-evaluable, evidence from the journal):
  tool_verified {tool}      the tool was used after the objective was created and its last outcome is ok
  verification_green        the newest verification record is GREEN and newer than the objective
  task_success              the objective's own task ended SUCCESS (weakest form of evidence; used for human goals)
  human                     never auto-completed; the objective waits BLOCKED for a person
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.logger import logger

from syrax import resources
from syrax import backup, contracts, estop, followup, plan
from syrax.journal import ALL_OBJECTIVES, BACKEND_ROOT, Journal, JournalError

REPO_ROOT_PATH = BACKEND_ROOT.parent

MAX_ATTEMPTS = 3
# mission 2026-10-28: SYRAX's own work per local day (the operator's forced cycles are not counted)
DAILY_TASKS = int(os.getenv("SYRAX_DAILY_TASKS", "40"))
CONTROLLER_STATES = ("OBSERVING", "SELECTING", "WORKING", "VERIFYING", "WAITING", "STOPPED", "DISABLED")
# Tools that cannot be exercised "harmlessly" without a real need: verifying them
# on their own would mean junk releases, junk skills, fake memories or uncited
# conclusions. Their evidence comes from real use.
NOT_AUTO_VERIFIED = frozenset({
    "release", "skill_create", "skill_test", "learn", "remember", "forget", "experiment", "present", "terminate", "ask_human",
    "compare_versions",
})
DEFAULT_INTERVAL_S = 120.0
# A quality objective is verified by a quality run, which needs an idle core:
# the cycle runs the suite itself, at most this often (free brain quotas).
QUALITY_MEASURE_EVERY_S = 6 * 3600.0
QUALITY_KINDS = ("quality_case_passes", "quality_recovered")
IDLE_INTERVAL_S = 600.0
NO_BRAIN_INTERVAL_S = 900.0  # after a task no brain answered: the network or every provider is down
MAINTENANCE_EVERY_S = 86400.0

AUTONOMOUS_BRIEF = (
    "[AUTONOMOUS OBJECTIVE] You are working on your own objective, not a human request.\n"
    "Goal: {goal}\nReason: {reason}\n{evidence}"
    "Your repository root is {repo_root}; paths in the goal are relative to it. Use absolute paths "
    "with every tool (python_execute runs elsewhere; str_replace_editor requires them). "
    "Read journaled tasks with `self_inspect` task_id and anything else with `journal_query` (read-only SQL), never python/sqlite3.\n"
    "Never weaken a check, test, benchmark or quality case to make it pass: fix the behaviour it measures. "
    "The files that judge or guard you (quality, verify, bench, autonomy, experiments, versions, devloop, "
    "limits, journal, guard, tools, permissions) and existing tests are changed only by a human; `release` refuses them here.\n"
    "Permission levels: in autonomous work a call that deletes, acts on the host (launch, volume, shell), sends, or writes outside "
    "the repository and workspace is refused with `Error: refused`; that is final, so do not plan such steps: do the rest and name what a human would have to do.\n"
    # live 2026-10-29 (level 3): asked to verify organize_folder, the brain pointed it at ~/Desktop and the kernel
    # refused; the brief now says where own work's code may reach, so the first attempt picks a place it can
    "Your code (python_execute, skills) runs inside a kernel boundary: it writes only in the workspace {workspace} "
    "(and your task worktree), reads the system, the venv and the repository (not backend/config), reaches only web "
    "ports 80/443, and sees no credentials. The owner's home folders (Desktop, Documents, Downloads) are out of reach: "
    "when a tool needs a folder or file, make one inside the workspace. The operator set your autonomy level to {level} "
    "({level_name}); a call above it is refused, and only the operator raises it.\n"
    "You cannot run the quality suite or start another SYRAX core from a task (the core is busy with you, "
    "and the journal refuses a second core): fix, `release`, and finish; the next cycle runs the quality suite. "
    "`release` is for repository changes only: a skill made with `skill_create` is live once VERIFIED and needs no release.\n"
    "Do the work with your tools. Your completion is judged from the journal evidence "
    "(which tools ran and whether they succeeded), not from what you say. Do not claim "
    "success you did not produce. Be economical: every step costs a model call; take the "
    "fewest steps that produce the evidence, do nothing unrelated, and then finish with one "
    "plain sentence stating exactly what you observed.{hint}"
)
# A code change needs read, edit, test, fix and release; the default 20 steps
# ran out live with a nearly finished change (objective 97, attempt 2).
RELEASE_STEPS = 30
# A brief that carries this phrase asks for a release; the agent checks for it
# before it lets such a task end with unreleased edits (agent.RELEASE_NUDGE).
RELEASE_MARK = "closes only when your `release` creates a commit"

BRIEF_HINTS = {
    # live 2026-10-14 (objective 224, attempt 1): the editor's str_replace missed four times on a region with em dashes,
    # the new test imported `backend.syrax.memory` and opened the running journal (read-only to other processes), and
    # thirty steps ran out before `release`. The hint now names the tools that avoid each of those.
    "change_released": (f" The objective {RELEASE_MARK}. You have {RELEASE_STEPS} steps: `repo_map` names the module and its test file; "
                        "read only the region you change; make the change and its NEW test file with `apply_patch` (one unified diff; "
                        "it compiles them and runs the covering tests and shows the result); fix forward with another patch; then `release`. "
                        "A test imports modules as `from syrax.<module> import ...` and uses tmp_path stores and journals the way the "
                        "module's existing test file does; a test that opens the running journal fails (read-only to other processes)."),
    "skill_verified": (" First `skill_list`: reuse or adapt a skill that already does this. Then `know`, `research` or `github_search` for"
                       " how it is done (an official API or a maintained library beats guessing). Build it with `skill_create`"
                       " (code + pytest tests, dependencies listed). The objective closes only when the skill `{name}` is VERIFIED"
                       " by its tests AND one real call of `{name}` afterwards succeeds: call it once with a realistic input."
                       " Write files only inside the workspace. Do not call `release`: a skill is not in the repository."),
    "tool_verified": (" For this objective one call of the `{tool}` tool with a harmless read-only action is enough; if it takes a "
                      "path, use a folder or file you make inside the workspace; report its output and finish."),
    "knowledge_stored": " Use `research` once on the stated topic, then `learn` one verified conclusion citing the knowledge_ids, then finish.",
    # Brief Factory phase 2 (repro.py): a hunt finds the code cause of a measured failure and proves it; it never
    # releases. Its own words override the brief's "fix, release" and the worktree note's "only release moves it in".
    "repro_proven": (" THIS OBJECTIVE IS A REPRO HUNT: do NOT call `release` (it is refused for a hunt). (1) Find the FIRST step where "
                     "SYRAX's own code (a tool, a nudge, a parser, a prompt rule) made the model's job wrong or told it something false: "
                     "read the evidence above, then `repo_map` and view only that function. If there is none, or it no longer happens, "
                     "answer `NO CODE CAUSE: <why>` and stop. (2) One `apply_patch` that creates ONE new file "
                     "backend/syrax/test_<topic>.py: a docstring with the evidence; `from syrax.<module> import ...`; tmp_path and "
                     "monkeypatch only (no network, shell or model, never the running journal); feed it the input that broke it, "
                     "quoted verbatim from the evidence (at least a dozen characters of the arguments, the error or the request); one "
                     "test for the behaviour the fix is for and one for what must keep working. Its reply must say TESTS FAIL. "
                     "(3) One `apply_patch` changing the module (never an existing test or a judge file) so the reply says TESTS PASS. "
                     "(4) Finish with one sentence: module, function, cause. The cycle proves the test and the fix on a clean tree and "
                     "files the brief that lands them."),
    "tool_reliability": " Follow the plan in the goal step by step. The objective closes only when new uses of `{tool}` show the lower failure rate, so finish by using it as the plan says.",
}


@dataclass
class CycleReport:
    started: float
    outcome: str  # RAN | IDLE | SKIPPED | DISABLED | BUSY | STOPPED (emergency stop)
    reason: Optional[str] = None
    objective_id: Optional[int] = None
    task_id: Optional[str] = None
    task_status: Optional[str] = None
    verdict: Optional[str] = None  # DONE | RETRY | BLOCKED
    derived: int = 0

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("started", "outcome", "reason", "objective_id", "task_id", "task_status", "verdict", "derived")}


PROPOSAL_KINDS = ("known_limitation", "brain_availability")


def proposal_from(objective: dict, task: Optional[dict]) -> Optional[dict]:
    """Phase 1, "next from what was learned": a researched limitation ends in
    a proposal for the human (what was found, what it would change, sources)
    instead of only a knowledge row nobody reads. SYRAX builds nothing here."""
    lim = ((objective.get("evidence") or {}).get("limitation")) or {}
    text = ((task or {}).get("result") or "").strip()
    if lim.get("kind") not in PROPOSAL_KINDS or not text:
        return None
    return {"objective_id": objective["id"], "limitation": lim.get("detail"), "kind": lim.get("kind"),
            "proposal": text[:1500], "sources": [u.rstrip(".,;:") for u in re.findall(r"https?://[^\s)\]]+", text)][:6]}


def strategy_of(events: List[dict]) -> List[str]:
    """How a task went about it: the distinct tool calls it made, each with
    its most telling argument, in order. Equal lists = the same strategy."""
    out: List[str] = []
    for e in events:
        if e["type"] != "tool.started":
            continue
        p = e["payload"]
        name = p.get("name") or "?"
        if name in ("terminate", "ask_human"):
            continue
        args = p.get("args") or {}
        if name == "python_execute":
            hint = " ".join(str(args.get("code") or "").split())[:40]
        elif name == "str_replace_editor":
            hint = f"{args.get('command')} {str(args.get('path') or '').replace(chr(92), '/').rsplit('/', 1)[-1]}"
        else:
            first = next(iter(args.values()), "") if args else ""
            hint = " ".join(str(first).split())[:40]
        sig = f"{name}({hint})"
        if sig not in out:
            out.append(sig)
    return out[:12]


# The fixed wording of generated goals (limits.py, followup.py and the generators in this file), read off the live
# objectives 2026-10-27: 106 of 320 goals start "My biggest measured limitation right now:" and restate their detail in
# a templated plan ("`research` how comparable systems overcome ... `learn` one verified conclusion with sources ...").
# Counted as shared words, that boilerplate let unrelated objectives recall each other ("push off by default" next to
# "task durations"), so it is removed before the goals are compared. The limitation's area heading ("Self-model: ",
# "Research engine + knowledge store: ") goes with it: two limitations of one area are not one subject.
_GOAL_TEMPLATE = [re.compile(t, re.S) for t in (
    r"My biggest measured limitation right now: (?:[A-Z][\w+/ -]{0,40}: )?",
    r"\. Improve it\. Plan: .*",
    r"Learn how to do what objective #\d+ could not: ",
    r"`research` it and `learn` one verified conclusion with sources\.",
    r"failed on its last use\. Diagnose why, then call it again with a harmless action that should succeed and report the result\.",
    r"Verify that the ",
    r"tool works on this machine by calling it with a harmless, read-only action and reporting exactly what it returned\.",
    r"The last verification run was BLOCKED \(failing gates: ",
    r"\)\. Investigate the failure output and report the root cause\.",
    r"A task failed with: ",
    r"\. Research the cause \(",
    r"\) with `research`, store what you learn with `learn`, and say what should change\.",
    r"Task quality regressed to [\d.]+% \([+-]?[\d.]+ pp\); failing cases: ",
    r"\. Inspect those tasks in the journal, find why the outcome was wrong, fix the cause in SYRAX's own code or prompts, release, and run the quality suite again\.",
    r" failed in the last two runs \(",
    r"\)\. Read the case in backend/syrax/quality\.py and the journaled task \S+ find the cause in SYRAX's own behaviour "
    r"\(code or prompts, never the case or its checks\), fix it and `release`; the objective closes when a newer quality run passes `[^`]*`\.",
    r"Quality case ",
    r"My knowledge contradicts itself: ",
    r"`research` it again from primary sources and `learn` the correct conclusion, citing them\.",
)]


def goal_words(goal: str) -> set:
    """The content words of a goal: its keywords once the generators' fixed wording is removed."""
    text = str(goal or "")
    for t in _GOAL_TEMPLATE:
        text = t.sub(" ", text)
    return set(auto_keywords(text))


def _experience_subject(o: dict) -> str:
    """What an objective is about: its check's tool, case, name or topic, else its limitation's subject."""
    spec = o.get("check_spec") or {}
    lim = (o.get("evidence") or {}).get("limitation") or {}
    s = spec.get("tool") or spec.get("case") or spec.get("name") or spec.get("topic") or lim.get("subject") or ""
    return " ".join(str(s).lower().split())


# A past objective is "similar" when it is about the same subject or shares this many content words with the goal.
# Same check kind alone no longer qualifies: live 2026-10-27, 801 of 1,100 recalled entries were DONE objectives that
# matched on kind (knowledge_stored, 3 points) plus templated goal words, with no subject in common.
EXPERIENCE_MIN_SHARED_WORDS = 3
FAILED_STATUSES = ("BLOCKED", "DROPPED")
# A word in more than this share of the closed goals is SYRAX's everyday vocabulary, not a subject: live 2026-10-27
# (320 closed) that is "task", "one", "only", "file", "syrax", "release", "backend", ... and the long hand-written
# change goals (100+ words) shared three of them with almost any limitation. Measured only on a pool big enough to
# say what is common.
EXPERIENCE_COMMON_SHARE = 0.08
EXPERIENCE_COMMON_MIN_POOL = 50


def past_experience(journal: Journal, objective: dict, limit: int = 3, budget: int = 900) -> str:
    """Phase 5: "last time this approach did badly because X, so this time Y".
    The closed objectives about the same subject, or sharing at least EXPERIENCE_MIN_SHARED_WORDS content words
    with this goal (generated boilerplate removed), with what worked or why they failed. Failed ones (BLOCKED,
    DROPPED) come first, as the Mission asks ("retrieval of relevant previous failures before repeating a
    workflow"); within each group, same subject, same check kind and shared words rank. Words common to more than
    EXPERIENCE_COMMON_SHARE of the closed goals do not count as shared."""
    spec = objective.get("check_spec") or {}
    subject = _experience_subject(objective)
    pool = [(o, goal_words(o.get("goal") or "")) for o in journal.objectives(limit=ALL_OBJECTIVES, status=["DONE", *FAILED_STATUSES])]
    common: set = set()
    if len(pool) >= EXPERIENCE_COMMON_MIN_POOL:
        df: Dict[str, int] = {}
        for _, ws in pool:
            for w in ws:
                df[w] = df.get(w, 0) + 1
        common = {w for w, n in df.items() if n > EXPERIENCE_COMMON_SHARE * len(pool)}
    words = goal_words(objective.get("goal") or "") - common
    scored = []
    for o, owords in pool:
        if o["id"] == objective.get("id"):
            continue
        same = bool(subject) and _experience_subject(o) == subject
        shared = len(words & owords)
        if not same and shared < EXPERIENCE_MIN_SHARED_WORDS:
            continue
        ospec = o.get("check_spec") or {}
        score = (3 if ospec.get("kind") == spec.get("kind") else 0) + (4 if same else 0) + shared
        scored.append((o["status"] in FAILED_STATUSES, score, o))
    if not scored:
        return ""
    lines = []
    for _, _, o in sorted(scored, key=lambda x: (not x[0], -x[1], -x[2]["updated"]))[:limit]:
        prog = o.get("progress") or {}
        log = prog.get("attempts_log") or []
        how = "; ".join((log[-1].get("strategy") or [])[:4]) if log else ""
        lines.append(f"- #{o['id']} {o['status']} after {o.get('attempts', 0)} attempt(s): {str(o['goal'])[:110]} — "
                     f"{str(prog.get('lesson') or '')[:150]}" + (f" (how: {how[:160]})" if how else ""))
    return ("Past experience with similar objectives (repeat what worked, avoid what failed):\n" + "\n".join(lines))[:budget] + "\n"


def rolled_back(events: List[dict]) -> Optional[dict]:
    """The attempt's own edits, rolled back because it ended without a committed
    release: where the diff was kept, so the next attempt can re-apply it
    instead of starting over (live: objective 97, attempt 2 ran out of steps
    with a nearly finished change, and attempt 3 would have started from zero)."""
    for e in reversed(events):
        p = e["payload"]
        if e["type"] == "rollback.created" and p.get("snapshot"):
            files = sorted(set((p.get("restored") or []) + (p.get("removed") or []))) or sorted(p.get("files") or {})
            return {"snapshot": p["snapshot"], "files": files}
    return None


def kept_diff(events: List[dict]) -> Optional[dict]:
    """rolled_back, or else the snapshot a release took before its gate (code.changed with "snapshot"): a task a
    restart cut short during its release has no rollback event, but its diff is kept all the same."""
    kept = rolled_back(events)
    if kept:
        return kept
    for e in reversed(events):
        p = e["payload"]
        if e["type"] == "code.changed" and p.get("snapshot"):
            return {"snapshot": p["snapshot"], "files": sorted(p.get("files") or {})}
    return None


def archive_brief(journal: Journal, objective: dict) -> str:
    """Phase 5: for an objective about SYRAX's own code, the archive of variants (running build's
    score, the best parent, this objective's dead ends). Empty for other objectives."""
    if (objective.get("check_spec") or {}).get("kind") != "change_released":
        return ""
    from syrax import archive
    from syrax.selfmodel import _git as _head

    try:
        return archive.brief(journal, _head(["rev-parse", "HEAD"], REPO_ROOT_PATH), objective.get("id"))
    except Exception:
        return ""


def brief_evidence(objective: dict, budget: int = 1800) -> str:
    """The evidence the objective was created from, compact, for the task.
    Live: SYRAX was told to "read the failures listed in the evidence" but the
    brief carried only the goal, so it guessed journal tables in raw SQL
    ("no such table: tool_calls", "no such column: id") instead."""
    ev = dict(objective.get("evidence") or {})
    ev.pop("plan", None)  # already in the goal
    ev.pop("plan_checks", None)  # shown as plan progress
    log = ((objective.get("progress") or {}).get("attempts_log")) or []
    tried = ""
    if log:
        tried = "Earlier attempts (do not repeat a failed strategy; change the approach):\n" + "\n".join(
            f"- attempt {a.get('attempt')} {a.get('verdict')}: {'; '.join(a.get('strategy') or ['no tools'])[:240]} — {a.get('lesson', '')[:160]}"
            for a in log[-4:]
        ) + "\n"
        last = log[-1]
        if last.get("kept"):
            tried += (f"The last attempt's edits to {', '.join(last.get('kept_files') or [])} were rolled back but kept as a diff at "
                      f"{last['kept']}: view it with str_replace_editor first and re-apply what was right instead of starting over.\n")
    if not ev:
        return tried
    lines = []
    for f in ev.pop("recent_failures", []) or []:
        lines.append(f"- task {f.get('task_id')}: {str(f.get('output') or '').strip()[-220:]}")
    head = json.dumps(ev, default=str, ensure_ascii=False)
    text = "Evidence: " + head[: budget // 2] + ("\nRecent failures (read more with self_inspect task_id):\n" + "\n".join(lines) if lines else "")
    return text[:budget] + "\n" + tried


LAUNCHER_PID_FILE = REPO_ROOT_PATH / "syrax.pid"


def _router():
    from syrax.brains import get_router

    return get_router()


def spawn_restart() -> None:
    """Start `syrax.py --respawn`, which starts the real restarter and exits:
    the restarter is then nobody's child, so stopping SYRAX's process tree
    does not kill it."""
    import subprocess
    import sys

    kw = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    subprocess.Popen([sys.executable, str(REPO_ROOT_PATH / "syrax.py"), "--respawn"], cwd=str(REPO_ROOT_PATH),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)


def resource_pressure() -> Optional[str]:
    """A reason string when the machine should not take on extra work, else None.
    Delegates to syrax.resources (CPU, RAM, disk, battery, quiet hours)."""
    return resources.pressure()


def own_work_may_not_call(journal: Journal, name: str) -> bool:
    """permissions.autonomous_refuses, or the level the skill registry recorded: skills
    are declared only when the agent is built, and a cycle right after a restart came
    first (live 2026-10-13: objective 183 asked own work to verify screen_brightness,
    a SYSTEM skill every own call of which is refused by design)."""
    from syrax import permissions

    if permissions.autonomous_refuses(name):
        return True
    row = journal.skill(name)
    risk = str(((row or {}).get("evidence") or {}).get("risk") or "")
    return bool(row) and row.get("status") == "VERIFIED" and risk in (permissions.SYSTEM, permissions.EXTERNAL_WRITE, permissions.DESTRUCTIVE)


SETTLE_EVENTS = ("knowledge.superseded", "knowledge.resolved")


def _derive_settle_objectives(journal: Journal) -> int:
    """Phase 5: contradicting conclusions are settled by fresh research. Derived from the rows' own DISPUTED state
    (fix-settle, 2026-10-27): reading the last 2000 events gave an older dispute no objective at all, and opened one
    for a pair already settled. A contradiction gets its objective while a row of it is still DISPUTED and another
    row of it is still believed (not SUPERSEDED, not forgotten); a DISPUTED row no open contradiction names gets one
    of its own. The check names the rows: it is met only once none of them is DISPUTED (judge)."""
    disputed = {k["id"]: k for k in journal.disputed_knowledge()}
    if not disputed:
        return 0
    created, covered = 0, set()
    for e in reversed(journal.events_of_type("knowledge.contradiction", limit=5000)):  # newest first
        p = e["payload"]
        ids = sorted({p.get("knowledge_id"), *(p.get("conflicts_with") or [])} - {None})
        open_ids = [i for i in ids if i in disputed]
        if not open_ids:
            continue  # settled (resolved or superseded) or forgotten: nothing to research
        live = [i for i in ids if i in disputed or ((journal.knowledge(int(i)) or {}).get("status") or "SUPERSEDED") != "SUPERSEDED"]
        if len(live) < 2:
            continue  # the other side is settled or gone: the row left is handled alone below
        covered.update(open_ids)
        ok = journal.add_objective_sync(
            goal=(f"My knowledge contradicts itself: id={p.get('knowledge_id')} says {str(p.get('claim'))[:160]!r} but "
                  f"{'; '.join(repr(c[:120]) for c in p.get('their_claims') or [])} (ids {ids}). `research` it again from primary "
                  "sources and `learn` the correct conclusion, citing them."),
            reason="two stored conclusions about the same thing disagree",
            priority=3, source="selfmodel", key=f"contradiction:{':'.join(map(str, ids))}",
            check={"kind": "knowledge_stored", "topic": " ".join((p.get("tags") or [])[:6]) or str(p.get("claim"))[:80], "disputed": ids},
            evidence={"knowledge_ids": ids},
        )
        created += bool(ok)
    for kid, k in disputed.items():
        if kid in covered:
            continue
        ok = journal.add_objective_sync(
            goal=(f"My knowledge contradicts itself: id={kid} says {str(k['claim'])[:160]!r} and is DISPUTED, but what it was "
                  f"disputed against is settled or gone (ids {[kid]}). `research` it again from primary "
                  "sources and `learn` the correct conclusion, citing them."),
            reason="a stored conclusion is still disputed and nothing open settles it",
            priority=3, source="selfmodel", key=f"contradiction:{kid}",
            check={"kind": "knowledge_stored", "topic": " ".join((k.get("tags") or [])[:6]) or str(k["claim"])[:80], "disputed": [kid]},
            evidence={"knowledge_ids": [kid]},
        )
        created += bool(ok)
    return created


def _disputed_ids(objective: dict) -> List[int]:
    """The rows a settle objective is about: its check's `disputed`, or, for one an older version created, the
    knowledge_ids of a `contradiction:` key."""
    spec = objective.get("check_spec") or {}
    ids = spec.get("disputed")
    if not ids and str(objective.get("key") or "").startswith("contradiction:"):
        ids = (objective.get("evidence") or {}).get("knowledge_ids")
    out = []
    for i in ids or []:
        try:
            out.append(int(i))
        except (TypeError, ValueError):
            continue
    return out


def _settlements(journal: Journal, objective: dict, ids: List[int]) -> List[dict]:
    """knowledge.superseded / knowledge.resolved events after the objective was set that settled one of `ids`."""
    want = set(ids)
    out = []
    for t in SETTLE_EVENTS:
        for e in journal.events_of_type(t, since=objective["created"], limit=5000):
            p = e["payload"]
            if t == "knowledge.superseded":
                if not (p.get("knowledge_ids") or []) and p.get("was") != "DISPUTED":
                    continue  # nothing was superseded and the winner was not disputed: it settled nothing
                named = {p.get("superseded_by"), *(p.get("knowledge_ids") or [])}
            else:
                named = {p.get("knowledge_id")}
            if want & named:
                out.append(e)
    return sorted(out, key=lambda e: e["id"])


def derive_objectives(journal: Journal, selfmodel: Any) -> int:
    """Turn evidence-based weaknesses into objectives. Idempotent via keys."""
    from syrax import repro  # with repro hunts on, some derivations give way to hunts

    created = 0
    caps = selfmodel.capabilities()
    created += _derive_settle_objectives(journal)
    # a traceback inside SYRAX's own code is a bug SYRAX can fix
    for e in journal.recent_events(300):
        if e["type"] != "tool.failed":
            continue
        out = str(e["payload"].get("output") or "")
        m = TRACE_IN_SYRAX.search(out)
        if not m:
            continue
        tool = e["payload"].get("name") or "?"
        path, line = m.group(1), m.group(2)
        ok = journal.add_objective_sync(
            goal=f"The `{tool}` tool raised inside SYRAX's own code at {path} line {line}: {out.strip().splitlines()[-1][:120]!r}. Read that code, fix the bug, add a new test in backend/syrax if one is missing, and `release`. Then call `{tool}` again the same way to confirm.",
            reason="a traceback in our own code is a defect with a known location",
            priority=2, source="selfmodel",
            check={"kind": "tool_verified", "tool": tool},
            key=f"tool-bug:{tool}:{path}:{line}",
            evidence={"event_id": e["id"], "traceback_tail": out[-600:]},
        )
        created += bool(ok)
    # one live objective per tool: repeated failures must not spawn a new objective each cycle
    targeted = {
        (o.get("check_spec") or {}).get("tool")
        for o in journal.objectives(limit=500, status=["OPEN", "ACTIVE", "BLOCKED"])
        if (o.get("check_spec") or {}).get("kind") == "tool_verified"
    }
    from syrax import permissions

    for c in caps:
        name = c["capability"]
        if not c["registered"] or name in NOT_AUTO_VERIFIED or name in targeted or own_work_may_not_call(journal, name):
            continue  # a tool own work may not call is verified by the human using it
        if c["status"] == "NOT_TESTED":
            ok = journal.add_objective_sync(
                goal=f"Verify that the `{name}` tool works on this machine by calling it with a harmless, read-only action and reporting exactly what it returned.",
                reason="no journal evidence that this capability works here",
                priority=5,
                source="selfmodel",
                check={"kind": "tool_verified", "tool": name},
                key=f"verify-capability:{name}",
                evidence={"capability": c},
            )
            created += bool(ok)
        elif c["status"] == "FAILING" and not repro.enabled():
            # with repro hunts on, a tool's own failure is hunted with a proof; a repair objective only called the
            # tool once more (34 of them in 14 days to 2026-10-22, no change)
            ok = journal.add_objective_sync(
                goal=f"The `{name}` tool failed on its last use. Diagnose why, then call it again with a harmless action that should succeed and report the result.",
                reason=f"last use failed ({c['failures']}/{c['uses']} failures)",
                priority=2,
                source="selfmodel",
                check={"kind": "tool_verified", "tool": name},
                key=f"repair-capability:{name}:{c['failures']}",
                evidence={"capability": c},
            )
            created += bool(ok)
    # objectives created for such tools by an earlier version are dropped, with the reason
    for o in journal.objectives(limit=500, status=["OPEN", "ACTIVE", "BLOCKED"]):
        spec = o.get("check_spec") or {}
        if spec.get("kind") == "tool_verified" and spec.get("tool") in NOT_AUTO_VERIFIED and o.get("source") == "selfmodel":
            journal.update_objective_sync(o["id"], status="DROPPED", note=f"{spec['tool']} is not auto-verified: it needs a real purpose")
    behavior = selfmodel.behavior()
    last_v = behavior["verifications"]["last"]
    # A gate that blocked a task's own candidate change says nothing about the code on main: the candidate
    # was rolled back and its objective already carries the failure. Live 2026-10-15: after each blocked
    # attempt of objective 232 the cycle spent a whole task on "investigate the blocked verification" and
    # named the wrong cause. A blocked gate with no task (a human's run) or the daily maintenance (docs
    # only, so a failure is main's) still becomes an objective.
    recent = journal.verifications(limit=1)
    owner = journal.task(recent[0].get("task_id")) if recent and recent[0].get("task_id") else None
    candidate = bool(owner) and not str(owner.get("goal") or "").startswith("[MAINTENANCE]")
    if last_v and last_v["status"] == "BLOCKED" and not candidate:
        failing = [g["name"] for g in last_v["gates"] if g["status"] != "PASS"]
        ok = journal.add_objective_sync(
            goal=f"The last verification run was BLOCKED (failing gates: {', '.join(failing) or 'unknown'}). Investigate the failure output and report the root cause.",
            reason="a blocked gate means the codebase is not releasable",
            priority=1,
            source="selfmodel",
            check={"kind": "verification_green"},
            key=f"verification-blocked:{int(last_v['ts'])}",
            evidence={"verification": last_v},
        )
        created += bool(ok)
    for f in behavior["recent_failures"]:
        if str(f.get("goal") or "").startswith("[MAINTENANCE]"):
            # maintenance runs judge code: a web search cannot fix it (live 2026-10-19, objective 299 researched a
            # TypeError raised in ledger.py); the failed task's error names the file and line for the human
            continue
        topic = _research_topic(f.get("error") or "")
        if topic:
            ok = journal.add_objective_sync(
                goal=f"A task failed with: {str(f.get('error'))[:160]!r}. Research the cause ({topic}) with `research`, store what you learn with `learn`, and say what should change.",
                reason="failure is information; a researched cause beats a blind retry",
                priority=3,
                source="selfmodel",
                check={"kind": "knowledge_stored", "topic": topic},
                key=f"research-failure:{f['task_id']}",
                evidence={"failure": f},
            )
            created += bool(ok)
    # ——— weaknesses of SYRAX's own mechanisms (recursive self-improvement) ———
    bench = journal.benchmarks(limit=1)
    if bench and bench[0]["status"] == "REGRESSION":
        for metric, d in bench[0]["deltas"].items():
            if d.get("regression"):
                ok = journal.add_objective_sync(
                    goal=f"Benchmark metric {metric} regressed from {d['before']} ms to {d['now']} ms ({d['pct']:+.1f}%). Find the cause in SYRAX's own code (journal/self-model/recovery), fix it, and release; the objective closes when a newer benchmark shows no regression for {metric}.",
                    reason="a slower mechanism is a measured weakness, not an opinion",
                    priority=2, source="selfmodel",
                    check={"kind": "benchmark_recovered", "metric": metric},
                    key=f"benchmark-regression:{metric}:{bench[0]['id']}",
                    evidence={"benchmark": {"id": bench[0]["id"], "delta": d}},
                )
                created += bool(ok)
    q = journal.quality_runs(limit=1)
    if q and q[0]["status"] == "REGRESSION":
        failed = [r["id"] for r in q[0]["results"] if not r.get("ok")]
        ok = journal.add_objective_sync(
            goal=f"Task quality regressed to {q[0]['pass_rate']}% ({q[0]['delta']:+.1f} pp); failing cases: {', '.join(failed)}. Inspect those tasks in the journal, find why the outcome was wrong, fix the cause in SYRAX's own code or prompts, release, and run the quality suite again.",
            reason="a lower pass rate on fixed tasks is a measured weakness of SYRAX itself",
            priority=2, source="selfmodel",
            check={"kind": "quality_recovered"},
            key=f"quality-regression:{q[0]['id']}",
            evidence={"quality": {"id": q[0]["id"], "failed": failed, "delta": q[0]["delta"]}},
        )
        created += bool(ok)
    # a quality case that failed in the last two runs is a defect to fix, not a fluke. With repro hunts on, a case
    # with a code cause is hunted (repro.py) and one without is the model's choice: the free-form objective is not
    # derived (24 of them, 2026-09-30..10-19, produced no commit; #217 and #283 tried to change the case's own files)
    runs = journal.quality_runs(limit=2) if not repro.enabled() else []
    if len(runs) == 2:
        failed_now = {r["id"]: r for r in runs[0]["results"] if not r.get("ok")}
        failed_before = {r["id"] for r in runs[1]["results"] if not r.get("ok")}
        for cid in sorted(set(failed_now) & failed_before):
            r = failed_now[cid]
            why = "; ".join(c["check"] + " → " + str(c.get("detail", ""))[:80] for c in r.get("checks", []) if not c.get("ok"))
            ok = journal.add_objective_sync(
                goal=f"Quality case `{cid}` failed in the last two runs ({why}). Read the case in backend/syrax/quality.py and the journaled task {r.get('task_id')}, find the cause in SYRAX's own behaviour (code or prompts, never the case or its checks), fix it and `release`; the objective closes when a newer quality run passes `{cid}`.",
                reason="a repeatable failure on a fixed task is a defect in SYRAX, not noise",
                priority=2, source="selfmodel",
                check={"kind": "quality_case_passes", "case": cid},
                key=f"quality-case:{cid}:{runs[0]['id']}",
                evidence={"quality_ids": [runs[0]["id"], runs[1]["id"]], "case": r},
            )
            created += bool(ok)
    blocked_tools: Dict[str, int] = {}
    for o in journal.objectives(limit=500, status="BLOCKED"):
        tool = (o.get("check_spec") or {}).get("tool")
        if tool:
            blocked_tools[tool] = blocked_tools.get(tool, 0) + 1
    for tool, n in blocked_tools.items():
        if n >= 2:
            ok = journal.add_objective_sync(
                goal=f"{n} objectives about the `{tool}` tool are BLOCKED after repeated failures. Research a genuinely different approach ({tool} alternative approach) with `research`, store what you find with `learn`, then propose the change.",
                reason="the same strategy failed repeatedly; change the strategy, not the retry count",
                priority=3, source="selfmodel",
                check={"kind": "knowledge_stored", "topic": f"{tool} alternative approach"},
                key=f"strategy-change:{tool}:{n}",
                evidence={"blocked": n},
            )
            created += bool(ok)
    for k in journal.knowledge_recent(limit=200):
        if k["uses"] >= 3 and k["confidence"] < 0.5 and k["kind"] in ("web", "conclusion"):
            ok = journal.add_objective_sync(
                goal=f"Knowledge #{k['id']} is used often ({k['uses']}x) but rests on weak evidence (confidence {k['confidence']:.2f}): {k['claim'][:120]!r}. Corroborate or refute it with `research` (more sources) and store the stronger result.",
                reason="frequently used beliefs deserve stronger evidence",
                priority=4, source="selfmodel",
                check={"kind": "knowledge_confidence", "knowledge_id": k["id"], "min": 0.6},
                key=f"corroborate:{k['id']}",
                evidence={"knowledge": {"id": k["id"], "confidence": k["confidence"], "uses": k["uses"]}},
            )
            created += bool(ok)
    for t in behavior["interrupted"]:
        if t["recovery_state"] == "UNCERTAIN":
            ok = journal.add_objective_sync(
                goal=f"Interrupted task {t['task_id']} ({t['goal'][:80]!r}) has an UNCERTAIN in-flight operation; a human must decide whether to resume or cancel it.",
                reason="never repeat an operation whose completion is unknown",
                priority=2,
                source="selfmodel",
                check={"kind": "human"},
                key=f"uncertain-task:{t['task_id']}",
                status="BLOCKED",
                evidence={"task": t},
                next_action="human: resume or cancel via the UI",
            )
            created += bool(ok)
    return created


def rejudge_blocked(journal: Journal) -> int:
    """BLOCKED objectives with a machine check are judged again on every cycle:
    evidence that arrives later (a quality run, a release, new tool uses) can
    satisfy them. Human checks and plain task_success stay blocked."""
    closed = 0
    for o in journal.objectives(limit=200, status="BLOCKED"):
        kind = (o.get("check_spec") or {}).get("kind", "task_success")
        if kind in ("human", "task_success"):
            continue
        verdict, evidence = judge(journal, o, None)
        verdict, contract = contracts.assess(journal, o, None, verdict, evidence, path="rejudge")
        if verdict == "DONE":
            journal.update_objective_sync(o["id"], status="DONE", evidence={"judged": evidence, "contract": contract, "task_id": None},
                                          progress={"lesson": "evidence that arrived after it was blocked satisfied it"},
                                          note="closed from newer evidence while blocked")
            closed += 1
    return closed


CHECK_ROOTS = (BACKEND_ROOT.parent,)  # file_* checks may look here only (the workspace is inside)


def check_path(raw: Any) -> Optional[Path]:
    """Resolve a file_present / file_absent path; None when it is not ours to check."""
    text = str(raw or "").strip()
    if not text:
        return None
    p = Path(text)
    if not p.is_absolute():
        p = CHECK_ROOTS[0] / p
    try:
        p = p.resolve()
    except OSError:
        return None
    for root in CHECK_ROOTS:
        try:
            p.relative_to(root.resolve())
            return p
        except ValueError:
            continue
    return None


def judge(journal: Journal, objective: dict, task: Optional[dict]) -> tuple[str, dict]:
    """Decide DONE / RETRY from journal evidence only. Returns (verdict, evidence)."""
    spec = objective.get("check_spec") or {}
    kind = spec.get("kind", "task_success")
    if kind == "human":
        return "BLOCKED", {"reason": "requires a human decision"}
    if kind == "tool_verified":
        st = journal.tool_stats().get(spec.get("tool"), None)
        used_after = bool(st and st["last_used"] and st["last_used"] >= objective["created"])
        ok = bool(st and st["last_outcome"] == "ok")
        ev = {"tool": spec.get("tool"), "used_after_objective": used_after, "last_outcome": st["last_outcome"] if st else None, "stats": st}
        return ("DONE" if used_after and ok else "RETRY"), ev
    if kind == "skill_verified":
        # Phase 3: a capability SYRAX built for itself counts only when its own
        # tests made it a VERIFIED tool after the objective was set
        name = str(spec.get("name") or "")
        sk = journal.skill(name)
        present = bool(sk and sk.get("path") and (Path(sk["path"]) / "skill.py").exists())  # live: VERIFIED in the registry, files deleted
        verified = bool(sk and sk.get("status") == "VERIFIED" and present and (sk.get("last_verified") or 0) >= objective["created"])
        # Audit 2026-10-29 (capability acquisition): VERIFIED meant only that the skill passed tests the same brain wrote
        # for it. The objective now also needs one real call of the skill, after that verification, that succeeded:
        # the capability did its job once outside its own tests. {"real_use": false} in the spec waives it.
        st = journal.tool_stats().get(name) if spec.get("real_use", True) else None
        used = (not spec.get("real_use", True)) or bool(
            st and st["last_used"] and st["last_used"] >= ((sk or {}).get("last_verified") or 0) and st["last_outcome"] == "ok")
        return ("DONE" if verified and used else "RETRY"), {
            "skill": name, "status": (sk or {}).get("status"), "files_present": present,
            "last_verified": (sk or {}).get("last_verified"), "real_use_ok": used,
            **({} if used else {"missing": "one real, successful call of the skill after it was verified"})}
    if kind == "tool_reliability":
        from syrax.limits import judge_tool_reliability
        return judge_tool_reliability(journal, objective)
    if kind == "knowledge_stored":
        topic_words = set(auto_keywords(spec.get("topic") or ""))
        rows = journal.knowledge_recent(limit=50, since=objective["created"])
        # a conclusion learned again is reinforced, not stored twice (consolidate.py): it still counts
        rows += [{"id": e["payload"].get("knowledge_id"), "claim": e["payload"].get("claim") or "", "tags": e["payload"].get("tags") or []}
                 for e in journal.events_between(objective["created"], limit=5000) if e["type"] == "knowledge.reinforced"]
        # only knowledge still believed counts (fix-settle, 2026-10-27): a row since SUPERSEDED (or forgotten) was
        # replaced, a DISPUTED one is contradicted by another stored row; neither is a verified conclusion
        believed: Dict[Any, bool] = {}
        for k in rows:
            kid = k.get("id")
            if kid is not None and kid not in believed:
                believed[kid] = ((journal.knowledge(int(kid)) or {}).get("status")) == "ACTIVE"
        rows = [k for k in rows if believed.get(k.get("id"))]
        hits = [k for k in rows if topic_words & set(auto_keywords(" ".join([k["claim"], k.get("question") or "", " ".join(k["tags"])])))]
        ev = {"topic": spec.get("topic"), "stored_after_objective": len(rows), "matching": [k["id"] for k in hits][:10]}
        ids = _disputed_ids(objective)
        if not ids:
            return ("DONE" if hits else "RETRY"), ev
        # a settle objective is met only when none of its rows is DISPUTED any more (resolved or superseded) and
        # either that settlement happened after it was set or a believed conclusion on the topic was stored after
        # it; a reinforcement alone, with the rows still DISPUTED, settles nothing
        states = {i: ((journal.knowledge(i) or {}).get("status") or "GONE") for i in ids}
        still = [i for i, s in states.items() if s == "DISPUTED"]
        settled = _settlements(journal, objective, ids)
        ev.update({"disputed": ids, "states": states, "still_disputed": still, "settled_by": [e["id"] for e in settled][:10]})
        return ("DONE" if not still and (settled or hits) else "RETRY"), ev
    if kind == "quality_case_passes":
        rows = journal.quality_runs(limit=1)
        case = spec.get("case")
        if rows and rows[0]["ts"] >= objective["created"]:
            hit = [r for r in rows[0]["results"] if r["id"] == case]
            ok = bool(hit and hit[0].get("ok"))
            return ("DONE" if ok else "RETRY"), {"case": case, "quality": rows[0]["id"], "passed": ok}
        return "RETRY", {"case": case, "quality": rows[0]["id"] if rows else None, "passed": None}
    if kind == "quality_recovered":
        rows = journal.quality_runs(limit=1)
        ok = bool(rows and rows[0]["ts"] >= objective["created"] and rows[0]["status"] != "REGRESSION")
        return ("DONE" if ok else "RETRY"), {"quality": rows[0]["id"] if rows else None, "status": rows[0]["status"] if rows else None}
    if kind == "benchmark_recovered":
        rows = journal.benchmarks(limit=1)
        ok = bool(rows and rows[0]["ts"] >= objective["created"] and not rows[0]["deltas"].get(spec.get("metric"), {}).get("regression"))
        return ("DONE" if ok else "RETRY"), {"metric": spec.get("metric"), "benchmark": rows[0]["id"] if rows else None, "status": rows[0]["status"] if rows else None}
    if kind == "knowledge_confidence":
        base = journal.knowledge(int(spec.get("knowledge_id") or 0))
        want = float(spec.get("min") or 0.6)
        tags = set((base or {}).get("tags") or [])
        # a DISPUTED row is contradicted by another stored row: it is not the stronger evidence asked for
        newer = [k for k in journal.knowledge_recent(limit=200, since=objective["created"])
                 if k["confidence"] >= want and (tags & set(k["tags"])) and k.get("status", "ACTIVE") == "ACTIVE"]
        return ("DONE" if newer else "RETRY"), {"knowledge_id": spec.get("knowledge_id"), "min": want, "stronger": [k["id"] for k in newer][:5]}
    if kind == "repro_proven":
        from syrax import repro

        return repro.judge_hunt(journal, objective, task)
    if kind == "change_released":
        # only a commit made by this objective's own tasks counts; someone
        # else's release landing in the window is not this objective's work
        ids = {task["task_id"]} if task and task.get("task_id") else set()
        window = journal.events_between(objective["created"], limit=5000)
        ids |= {e["payload"].get("task_id") for e in window
                if e["type"] == "cycle.completed" and e["payload"].get("objective_id") == objective.get("id") and e["payload"].get("task_id")}
        # a task-less commit event (recorded from outside any task) keeps counting
        commits = [e for e in window if e["type"] == "commit.created" and (e.get("task_id") is None or e.get("task_id") in ids)]
        # A check that names files is met only when this objective's commits, together, changed every one of them.
        # Live 2026-10-17 (objective 267): step 1 of three landed alone (09e97df) and any commit counted as DONE.
        touched = {f for e in commits for f in (e["payload"].get("files") or [])}
        missing = [f for f in spec.get("files") or [] if f not in touched]
        verdict = "DONE" if commits and not missing else "RETRY"
        ev = {"commits": [e["payload"].get("commit") for e in commits][:5], "tasks": sorted(ids), **({"missing_files": missing} if missing else {})}
        if verdict == "DONE" and isinstance(spec.get("repro"), dict):
            # a brief filed with a judge-proven test is done only when that very test was committed (repro.py)
            from syrax import repro

            ev["repro"] = repro.fidelity(REPO_ROOT_PATH, [e["payload"].get("commit") for e in commits], spec["repro"])
            verdict = "DONE" if ev["repro"].get("ok") else "RETRY"
        return verdict, ev
    if kind in ("file_present", "file_absent"):
        # a world-state check: the file must be inside the repository or the
        # workspace, and a present file counts only if it changed after the
        # objective was set (evidence that work happened, not that it existed)
        path = check_path(spec.get("path"))
        if path is None:
            return "BLOCKED", {"reason": f"path {spec.get('path')!r} is outside the repository and workspace; a human must check it"}
        exists = path.exists()
        mtime = path.stat().st_mtime if exists else None
        ok = (not exists) if kind == "file_absent" else bool(exists and mtime is not None and mtime >= objective["created"] - 1)
        return ("DONE" if ok else "RETRY"), {"path": str(path), "exists": exists, "mtime": mtime}
    if kind == "verification_green":
        rows = journal.verifications(limit=1)
        ok = bool(rows and rows[0]["status"] == "GREEN" and rows[0]["ts"] >= objective["created"])
        return ("DONE" if ok else "RETRY"), {"verification": rows[0] if rows else None}
    status = (task or {}).get("status")
    return ("DONE" if status == "SUCCESS" else "RETRY"), {"task_status": status, "result": (task or {}).get("result")}


class Autonomy:
    def __init__(self, core: Any, journal: Optional[Journal] = None):
        self.core = core
        self.journal = journal or core.journal
        self.interval = float(os.getenv("SYRAX_CYCLE_INTERVAL", DEFAULT_INTERVAL_S))
        # Phase 1: when idle, rank own limitations and work on the strongest
        self.reflect = os.getenv("SYRAX_REFLECT", "1") != "0"
        self.reports: List[CycleReport] = []
        self.state: dict = {}
        self._loop_task: Optional[asyncio.Task] = None
        self._cycle_running = False
        self.recover_active("process restarted")

    def recover_active(self, why: str) -> int:
        """An ACTIVE objective with no cycle running is a lie left by a dead or
        cancelled cycle: put it back to OPEN so it can be picked again."""
        n = 0
        for o in self.journal.objectives(limit=500, status="ACTIVE"):
            progress = self._interrupted_attempt(o)
            self.journal.update_objective_sync(o["id"], status="OPEN", note=f"reopened: {why}", **({"progress": progress} if progress else {}))
            n += 1
        return n

    def _interrupted_attempt(self, objective: dict) -> Optional[dict]:
        """The objective's task that a restart interrupted, as an attempts_log entry with its kept diff. Live
        2026-10-17: objective 267's release was cut by a shutdown after its preflight passed, its diff was kept by
        the release's snapshot, and the next attempt started from zero because nothing pointed to it."""
        tasks = [t for t in self.journal.tasks(limit=20, status="INTERRUPTED")
                 if t.get("kind") == "autonomous" and t.get("goal") == objective["goal"]]
        if not tasks:
            return None
        task = tasks[0]
        log = list(((objective.get("progress") or {}).get("attempts_log")) or [])
        if any(a.get("task_id") == task["task_id"] for a in log):
            return None
        events = self.journal.events(task["task_id"], limit=5000)
        kept = kept_diff(events)
        log.append({"attempt": objective.get("attempts", 0), "task_id": task["task_id"], "verdict": "INTERRUPTED",
                    "strategy": strategy_of(events), "lesson": "a restart interrupted it before it finished; nothing landed",
                    **({"kept": kept["snapshot"], "kept_files": kept["files"][:6]} if kept else {})})
        return {"attempts_log": log[-6:]}

    # ——— enable / disable (persisted) ———

    @property
    def enabled(self) -> bool:
        """On when the operator turned it on (or SYRAX_AUTONOMY=1 and the operator never chose), never while the
        emergency stop is on. Audit 2026-10-28: SYRAX_AUTONOMY=1 overrode the operator's "off" (the UI said off,
        the next boot started the loop); the environment may still force it off, but no longer over a human's off."""
        if estop.active(self.journal):
            return False
        env = os.getenv("SYRAX_AUTONOMY")
        if env == "0":
            return False
        saved = self.journal.get_meta("autonomy_enabled")
        if saved is not None:
            return saved == "1"
        return env == "1"

    @property
    def level(self) -> int:
        """The operator's autonomy level, 1-5 (permissions.LEVEL_NAMES); 5 when never set (before levels existed)."""
        try:
            return max(1, min(5, int(self.journal.get_meta("autonomy_level") or 5)))
        except ValueError:
            return 1  # an unreadable level is the most careful one

    def set_level(self, level: int, by: str = "operator") -> int:
        level = max(1, min(5, int(level)))
        self.journal.set_meta("autonomy_level", str(level))
        self.journal.record_sync("autonomy.level_set", {"level": level, "by": by[:120]})
        return level

    def set_enabled(self, on: bool, by: Optional[str] = None) -> None:
        self.journal.set_meta("autonomy_enabled", "1" if on else "0")
        # who turned it on or off (2026-10-29: autonomy came back on 35 s after an operator's "off" and the record could
        # not say from where)
        self.journal.record_sync("autonomy.toggled", {"enabled": on, **({"by": by[:160]} if by else {})})

    async def set_enabled_async(self, on: bool, by: Optional[str] = None) -> None:
        await self.journal.run(self.set_enabled, on, by)

    def _saved_state(self) -> dict:
        try:
            return json.loads(self.journal.get_meta("autonomy_state") or "{}")
        except ValueError:
            return {}

    def status(self) -> dict:
        last = self.reports[-1].to_dict() if self.reports else None
        counts = {st: 0 for st in ("OPEN", "ACTIVE", "DONE", "BLOCKED", "DROPPED")}
        for o in self.journal.objectives(limit=ALL_OBJECTIVES):
            counts[o["status"]] += 1
        snap = resources.snapshot()
        return {
            "enabled": self.enabled,
            "estop": estop.state(self.journal),
            "level": self.level,
            "state": self.state or self._saved_state(),
            "autonomous_today": self.autonomous_today(),
            "daily_tasks": DAILY_TASKS,
            "running_loop": self._loop_task is not None and not self._loop_task.done(),
            "interval_s": self.interval,
            "last_cycle": last,
            "cycles": len(self.reports),
            "objectives": counts,
            "resources": snap,
            "pressure": resources.pressure(snap),
            "last_maintenance": self.journal.get_meta("last_maintenance"),
        }

    # ——— controller state and selection record (mission 2026-10-28) ———

    async def _state(self, name: str, **info) -> None:
        """The controller's state (OBSERVING, SELECTING, WORKING, VERIFYING, WAITING, STOPPED, DISABLED), kept in the
        journal's meta so a restart and the operator read it; a change of state is journaled as autonomy.state."""
        if name not in CONTROLLER_STATES:
            raise ValueError(name)
        prev = self.state.get("state")
        self.state = {"state": name, "at": time.time(), **{k: v for k, v in info.items() if v is not None}}
        await self.journal.run(self.journal.set_meta, "autonomy_state", json.dumps(self.state, default=str))
        if name != prev:
            await self.journal.record("autonomy.state", {"from": prev, **self.state})

    async def _selected(self, objective: dict) -> None:
        """Why this objective: its own reason, evidence and check, and the open alternatives it was chosen over
        (priority, then age: journal.objectives / _pick)."""
        others = [o for o in self.journal.objectives(limit=6, status="OPEN") if o["id"] != objective["id"]][:3]
        spec = objective.get("check_spec") or objective.get("check") or None
        await self.journal.record("goal.selected", {
            "objective_id": objective["id"], "goal": str(objective.get("goal") or "")[:200],
            "priority": objective.get("priority"), "reason": str(objective.get("reason") or "")[:300],
            "attempts": objective.get("attempts"), "success_check": spec if isinstance(spec, (dict, str)) else None,
            "rule": "highest priority, then oldest, among OPEN objectives whose dependencies are done",
            "alternatives": [{"id": o["id"], "priority": o.get("priority"), "goal": str(o.get("goal") or "")[:120]} for o in others],
        })
        await self._state("WORKING", objective_id=objective["id"])

    def autonomous_today(self) -> int:
        """This PC's autonomous tasks started since local midnight: counted in the journal, never among a newest-500
        window, and without tasks merged in from another PC's journal (Journal.own_tasks_since)."""
        midnight = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        return self.journal.own_tasks_since(midnight, kind="autonomous")

    # ——— one cycle ———

    def _pick(self) -> Optional[dict]:
        done = {o["id"] for o in self.journal.objectives(limit=ALL_OBJECTIVES, status="DONE")}
        for o in self.journal.objectives(limit=500, status="OPEN"):
            if all(d in done for d in (o.get("dependencies") or [])):
                return o
        return None

    async def _roll_back_regressions(self) -> None:
        """A skill whose new version keeps failing in real use while the kept one before it worked goes back to that
        version (skillevo.regressions; audit 2026-10-29). At level 3 and up only: it changes what SYRAX can do. The
        replaced code is kept, so the human's skill_rollback undoes it. Journaled skill.regression, then the rollback's
        own skill.rolled_back."""
        factory = getattr(self.core, "skills", None)
        if factory is None or self.level < 3:
            return
        from syrax import skillevo

        try:
            found = await self.journal.run(skillevo.regressions, self.journal, factory.kept_versions)
        except Exception as e:  # measuring must never kill the cycle
            logger.warning(f"skill regression check failed: {e}")
            return
        for r in found:
            try:
                await self.journal.record("skill.regression", {**r, "action": "rolled back to the kept version"})
                await factory.rollback(r["skill"])
            except Exception as e:
                logger.warning(f"rolling back {r['skill']} failed: {e}")

    async def run_once(self, force: bool = False) -> CycleReport:
        """One bounded cycle. ``force`` ignores the enabled flag (manual `cycle_now`), never the emergency stop."""
        rep = CycleReport(started=time.time(), outcome="IDLE")
        if estop.active(self.journal):
            rep.outcome, rep.reason = "STOPPED", "emergency stop is on"
            return await self._finish(rep)
        if not force and not self.enabled:
            rep.outcome, rep.reason = "DISABLED", "autonomy is off"
            return await self._finish(rep)
        measuring = bool(getattr(getattr(self.core, "quality", None), "running", False))
        queued = getattr(self.core, "queued", None)
        waiting = bool(queued()) if callable(queued) else False  # a human request waits: it goes first (2026-10-25)
        if self.core.busy or self._cycle_running or measuring or waiting:
            rep.outcome, rep.reason = "BUSY", ("a task is already running" if self.core.busy else
                                               "a quality run is measuring" if measuring else
                                               "a human request is waiting in the queue" if waiting else "a cycle is already running")
            return await self._finish(rep)
        self._cycle_running = True
        try:
            return await self._run_cycle(rep, force)
        finally:
            self._cycle_running = False

    async def _run_cycle(self, rep: CycleReport, force: bool) -> CycleReport:
        pressure = resource_pressure()
        if pressure and not force:
            rep.outcome, rep.reason = "SKIPPED", pressure
            return await self._finish(rep)
        if await self._restart_if_pending(rep):
            return await self._finish(rep)
        spent = await asyncio.to_thread(self.autonomous_today)
        if spent >= DAILY_TASKS and not force:
            # mission 2026-10-28: a daily budget for SYRAX's own work (the operator's cycle_now is not counted against it)
            rep.outcome, rep.reason = "SKIPPED", f"daily budget spent: {spent} of {DAILY_TASKS} autonomous tasks today (SYRAX_DAILY_TASKS)"
            return await self._finish(rep)
        await self._state("OBSERVING")
        await self.journal.record("cycle.started", {"forced": force})
        try:
            rep.derived = await self.journal.run(derive_objectives, self.journal, self.core.selfmodel)
        except Exception as e:  # deriving must never kill the cycle
            logger.warning(f"objective derivation failed: {e}")
        try:
            await self.journal.run(rejudge_blocked, self.journal)
        except Exception as e:
            logger.warning(f"re-judging blocked objectives failed: {e}")
        try:  # Brief Factory phase 2: a measured failure with a code cause becomes one repro hunt
            from syrax import repro

            if repro.enabled():
                rep.derived = (rep.derived or 0) + await self.journal.run(repro.derive, self.journal)
        except Exception as e:
            logger.warning(f"repro hunt derivation failed: {e}")
        if os.getenv("SYRAX_FEATURES", "0") == "1":
            try:  # every cycle, not only when idle: a feature that broke is open work
                from syrax import catalog

                await self.journal.run(catalog.reopen_regressed, self.journal)
            except Exception as e:
                logger.warning(f"re-checking catalog features failed: {e}")
        await self._roll_back_regressions()
        await self._state("SELECTING")
        objective = self._pick()
        if objective is None and self.reflect:
            # Phase 1: nothing is failing loudly, so ask what limits SYRAX most
            # and work on that instead of idling.
            try:
                from syrax.limits import choose

                chosen = await self.journal.run(choose, self.journal, self.core.selfmodel)
                if chosen:
                    rep.derived += 1
                    objective = self._pick()
            except Exception as e:  # choosing must never kill the cycle
                logger.warning(f"limitation ranking failed: {e}")
        if objective is None and self.reflect and os.getenv("SYRAX_FEATURES", "0") == "1":
            # nothing limits SYRAX right now: take up the next low-risk feature from the catalog
            try:
                from syrax import catalog

                feature = await self.journal.run(catalog.next_auto, self.journal)
                if feature is not None:
                    await self.journal.run(catalog.promote, self.journal, feature.id, "catalog")
                    rep.derived += 1
                    objective = self._pick()
            except Exception as e:
                logger.warning(f"feature catalog failed: {e}")
        if objective is None and self.reflect and os.getenv("SYRAX_RADAR", "1") != "0":
            # Phase 6: idle time is when SYRAX looks outward (new models on its brains)
            try:
                from syrax import radar

                if await asyncio.to_thread(radar.due, self.journal):
                    router = _router()
                    found = await radar.scan(router, self.journal)
                    rep.outcome = "RAN"
                    rep.reason = (f"radar: {sum(len(v) for v in found['new'].values())} new model(s), "
                                  f"{len(found['tested'])} tested, baseline for {', '.join(found['baselined']) or 'none'}")
                    return await self._finish(rep)
            except Exception as e:
                logger.warning(f"technology radar failed: {e}")
        if objective is None:
            rep.outcome, rep.reason = "IDLE", "no open objective"
            if os.getenv("SYRAX_PUBLISH_RISE", "0") == "1":
                from syrax import ledger

                if ledger.due(self.journal):
                    # M3: the evidence publishes itself, through SYRAX's own isolated release
                    try:
                        res = await ledger.publish(self.journal, reviewer=getattr(getattr(self.core, "devloop", None), "reviewer", None),
                                                   matrix=True)
                        rep.outcome, rep.reason = "RAN", f"published the rise ledger: {res.get('outcome')}"
                    except Exception as e:
                        logger.warning(f"publishing the rise ledger failed: {e}")
                    return await self._finish(rep)
            if os.getenv("SYRAX_CODEBENCH", "0") == "1":
                from syrax import codebench

                if await asyncio.to_thread(codebench.due, self.journal):
                    # M2: measure which brain finishes code changes, so releases start on it
                    try:
                        res = await codebench.run_all(self.core)
                        rep.outcome, rep.reason = "RAN", f"code benchmark: {codebench.summary(res)}"
                    except Exception as e:
                        logger.warning(f"the code benchmark failed: {e}")
                    return await self._finish(rep)
            runner = getattr(self.core, "quality", None)
            if self.reflect and runner is not None:
                # phase 3 of the Brief Factory: SYRAX measures itself daily (repro.measure_subset), so a failure is
                # seen twice before a hunt and a landed fix is measured again
                from syrax import repro

                if repro.enabled() and await asyncio.to_thread(repro.measure_due, self.journal):
                    try:
                        from syrax import quality

                        only = repro.measure_subset(self.journal, [c["id"] for c in quality._cases(quality.WORKSPACE)])
                        row = await runner.run(only=only)
                        rep.outcome, rep.reason = "RAN", (f"self-measurement: quality run #{row.get('id')} on {len(only)} "
                                                          f"cases, {row.get('pass_rate')}%")
                    except Exception as e:
                        logger.warning(f"self-measurement failed: {e}")
                    return await self._finish(rep)
            if os.getenv("SYRAX_FEATURES", "0") == "1":
                from syrax import topics

                if await asyncio.to_thread(topics.due, self.journal):
                    # the human's watched topics, once a day: only stories not reported before
                    try:
                        found = await topics.check(self.journal)
                        rep.outcome, rep.reason = "RAN", f"watched topics: {sum(len(f['items']) for f in found)} new stories"
                    except Exception as e:
                        logger.warning(f"watched topics failed: {e}")
                    return await self._finish(rep)
            try:
                # the evidence copies itself once a day (verified; backup.KEEP kept), before maintenance prunes anything
                if await asyncio.to_thread(backup.due, self.journal):
                    m = await self.journal.run(backup.snapshot, self.journal)
                    # and is restored once, aside, to prove it would come back whole (backup.rehearse, wave 1)
                    await asyncio.to_thread(backup.rehearse, m["dir"], self.journal)
                    gone = await asyncio.to_thread(backup.prune, Path(m["dir"]).parent)
                    rep.reason = f"no open objective; backup: {Path(m['dir']).name}, {m['bytes']} bytes, {len(gone)} old pruned"
            except Exception as e:  # snapshot journaled backup.failed; the cycle goes on
                logger.warning(f"backup failed: {e}")
            if self.journal.maintenance_due(MAINTENANCE_EVERY_S):
                # useful idle work: keep the journal bounded (measured, journaled)
                try:
                    m = await self.journal.run(self.journal.maintain)
                    rep.reason = f"{rep.reason}; maintenance: pruned {m['events_pruned']} events, trimmed {m['checkpoint_contexts_trimmed']} contexts"
                except Exception as e:
                    logger.warning(f"maintenance failed: {e}")
            return await self._finish(rep)
        rep.objective_id = objective["id"]
        await self._selected(objective)
        if contracts.needs_a_check(objective):
            # no task is spent on an objective that nothing could ever prove done
            await self.journal.update_objective(objective["id"], status="BLOCKED", note=contracts.NOT_VERIFIABLE,
                                                next_action="attach a machine check, or close it by hand")
            rep.outcome, rep.verdict, rep.reason = "RAN", "BLOCKED", contracts.NOT_VERIFIABLE
            return await self._finish(rep)
        # Evidence may already satisfy the objective (e.g. the tool ran for another
        # objective). Then there is no work to do: close it, run nothing.
        verdict, evidence = await asyncio.to_thread(judge, self.journal, objective, None)
        verdict, contract = await asyncio.to_thread(contracts.assess, self.journal, objective, None, verdict, evidence, "existing")
        if verdict == "DONE":
            await self.journal.update_objective(
                objective["id"], status="DONE", evidence={"judged": evidence, "contract": contract, "task_id": None},
                progress={"lesson": "already satisfied by existing evidence; no task needed"},
                note="closed from existing evidence",
            )
            rep.outcome, rep.verdict, rep.reason = "RAN", "DONE", "satisfied by existing evidence"
            return await self._finish(rep)
        if await self._measure_quality(objective, rep):
            return await self._finish(rep)
        await self.journal.update_objective(
            objective["id"], status="ACTIVE",
            progress={"cycle_started": rep.started}, note="cycle picked this objective",
        )
        spec = objective.get("check_spec") or {}
        hint = BRIEF_HINTS.get(spec.get("kind", ""), "").format(**{k: v for k, v in spec.items() if isinstance(v, str)})
        if spec.get("kind") == "change_released" and spec.get("files"):
            hint += (" It is done only when your released commits, together, change: " + ", ".join(spec["files"])
                     + "; a release of part of it is progress, not the end.")
        from syrax.devloop import REPO_ROOT

        steps_before = await asyncio.to_thread(plan.status, self.journal, objective, plan.task_ids_of(objective))
        from syrax.permissions import LEVEL_NAMES, WORKSPACE

        level = await asyncio.to_thread(lambda: self.level)
        brief = AUTONOMOUS_BRIEF.format(goal=objective["goal"], reason=objective.get("reason") or "-", hint=hint, repo_root=REPO_ROOT,
                                        workspace=WORKSPACE, level=level, level_name=LEVEL_NAMES.get(level, "?"),
                                        evidence=plan.render(steps_before) + followup.learned_brief(self.journal, objective)
                                        + brief_evidence(objective) + past_experience(self.journal, objective)
                                        + archive_brief(self.journal, objective))
        if getattr(getattr(self.core, "quality", None), "running", False):
            # a quality run began while this cycle built the brief (live 2026-10-15, run #44): it goes first
            await self.journal.update_objective(objective["id"], status="OPEN", note="a quality run started first")
            rep.outcome, rep.reason = "BUSY", "a quality run is measuring"
            return await self._finish(rep)
        try:
            budget = {"max_steps": RELEASE_STEPS} if spec.get("kind") in ("change_released", "repro_proven") else {}
            rp = spec.get("repro") if isinstance(spec.get("repro"), dict) else None
            if budget and rp and rp.get("test") and rp.get("text"):
                budget["seed"] = {rp["test"]: rp["text"]}  # the proven test is written, not retyped by a model
            task_id = await self.core.submit(brief, said=objective["goal"], session_id=None, kind="autonomous", **budget)
        except RuntimeError as e:  # e.g. the agent could not be built: the objective must not stay ACTIVE
            await self.journal.update_objective(objective["id"], status="OPEN", note=f"could not start: {e}")
            rep.outcome, rep.reason = "SKIPPED", f"could not start the task: {e}"
            return await self._finish(rep)
        if task_id is None:
            if await asyncio.to_thread(estop.active, self.journal):  # the stop met the task at its start (core._begin_now)
                await self.journal.update_objective(objective["id"], status="OPEN", note="emergency stop: not an attempt")
                rep.outcome, rep.reason = "STOPPED", "emergency stop is on"
                return await self._finish(rep)
            await self.journal.update_objective(objective["id"], status="OPEN", note="core busy")
            rep.outcome, rep.reason = "BUSY", "core refused the task"
            return await self._finish(rep)
        rep.task_id = task_id
        await self.core.wait()
        task = self.journal.task(task_id) or {}
        rep.task_status = task.get("status")
        rep.outcome = "RAN"
        if task.get("status") == "FAILED" and no_brain_answered(self.journal, task_id):
            # Live 2026-10-15, 12:54-15:35 (the network was down): every three minutes the cycle started a task
            # that failed at its first brain call, counted it as an attempt, blocked objective 237 and four more,
            # and derived nested "learn how to do what #239 could not" follow-ups from the outage itself.
            await self.journal.update_objective(objective["id"], status="OPEN", last_task_id=task_id,
                                                note="no brain could be reached: not an attempt")
            rep.outcome, rep.reason = "NO_BRAIN", "no brain could be reached; the objective stays open"
            return await self._finish(rep)
        if task.get("status") == "CANCELLED" and await asyncio.to_thread(estop.active, self.journal):
            # Audit 2026-10-29: an E-STOP during a forced cycle (cycle_now runs detached, so stopping the loop does not
            # end it) cancelled the task, which was then judged a failed attempt: three of them BLOCKED the objective
            # and derived follow-ups while the stop was on. The operator's stop is never the objective's failure.
            await self.journal.update_objective(objective["id"], status="OPEN", last_task_id=task_id,
                                                note="emergency stop: not an attempt")
            rep.outcome, rep.reason = "STOPPED", "emergency stop is on; the objective stays open"
            return await self._finish(rep)
        if spec.get("kind") == "repro_proven":
            # what the hunt left in its worktree is judged by code: screened, bound to the evidence, proved, filed
            from syrax import repro

            try:
                await asyncio.to_thread(repro.harvest, self.journal, objective, task)
            except Exception as e:
                logger.warning(f"repro harvest failed: {e}")
        await self._state("VERIFYING", objective_id=objective["id"], task_id=task_id)
        # ——— reflect: expected vs actual, judged from evidence ———
        verdict, evidence = await asyncio.to_thread(judge, self.journal, objective, task)
        judged = verdict
        verdict, contract = await asyncio.to_thread(contracts.assess, self.journal, objective, task, verdict, evidence, "task")
        rep.verdict = verdict
        attempts = objective["attempts"] + 1
        lesson = _lesson(objective, task, verdict, evidence)
        if judged == "DONE" and verdict != "DONE":  # the check read as met, the contract withdrew it
            lesson = f"not done: {contract['reason']}"
        # Phase 2: remember how this attempt went about it; a strategy that
        # already failed is not tried again (no blind retry)
        task_events = self.journal.events(task_id)
        strategy = strategy_of(task_events)
        kept = rolled_back(task_events) if verdict != "DONE" else None
        if verdict != "DONE" and task.get("status") == "PARTIAL":
            # a PARTIAL is a step limit or loop stop, or (since 2026-10-27) an answer whose claim survived its nudge
            # (core._run: task.completed {reason: "claim_unproven", check}); the lesson names which one it was
            done = next((e["payload"] for e in reversed(task_events) if e["type"] == "task.completed"), {}) or {}
            if done.get("reason") == "claim_unproven":
                lesson = f"its answer claimed what no tool showed ({done.get('check')}); {lesson}"
            else:
                lesson = f"ran out of steps; {lesson}"
        log = list(((objective.get("progress") or {}).get("attempts_log")) or [])
        # Phase 1: which plan steps the journal now proves, across all attempts
        steps = await asyncio.to_thread(plan.status, self.journal, objective, plan.task_ids_of(objective, task_id))
        advanced = plan.proven(steps) > plan.proven(steps_before)
        nxt = plan.next_step(steps)
        if steps and verdict != "DONE":
            lesson = f"{lesson} Plan: {plan.proven(steps)}/{len(steps)} steps proven" + (f"; resume at step {nxt['step']}" if nxt else "") + "."
        if advanced:
            await self.journal.record("plan.progressed", {"objective_id": objective["id"], "task_id": task_id, **plan.summary(steps)})  # the task is closed
        # a repeated strategy is blind only when it proved nothing new
        repeated = verdict != "DONE" and not advanced and any(a.get("strategy") == strategy and a.get("verdict") != "DONE" for a in log)
        if repeated:
            lesson = f"repeated the strategy of an earlier failed attempt ({', '.join(strategy[:4]) or 'no tools'}); {lesson}"
        log.append({"attempt": attempts, "task_id": task_id, "verdict": verdict, "strategy": strategy, "lesson": lesson[:300],
                    **({"steps_proven": plan.proven(steps)} if steps else {}),
                    **({"kept": kept["snapshot"], "kept_files": kept["files"][:6]} if kept else {})})
        if repeated:
            verdict = "BLOCKED"
        if verdict == "DONE":
            await self.journal.update_objective(
                objective["id"], status="DONE",
                progress={"lesson": lesson, "attempts_log": log[-6:]}, evidence={"judged": evidence, "contract": contract, "task_id": task_id},
                last_task_id=task_id, bump_attempts=True, note=lesson,
            )
            proposal = proposal_from(objective, task)
            if proposal:
                await self.journal.record("proposal.created", {**proposal, "task_id": task_id})  # the task is closed; the event stands alone
        elif verdict == "BLOCKED" or attempts >= MAX_ATTEMPTS:
            rep.verdict = "BLOCKED"
            await self.journal.update_objective(
                objective["id"], status="BLOCKED",
                progress={"lesson": lesson, "attempts_log": log[-6:]}, evidence={"judged": evidence, "contract": contract, "task_id": task_id},
                last_task_id=task_id, bump_attempts=True,
                next_action="needs a different strategy or a human", note=lesson,
            )
            # Phase 1: what this attempt taught decides the next objective
            blocked = await asyncio.to_thread(self.journal.objective, objective["id"])
            await asyncio.to_thread(followup.drop_dependents, self.journal, objective["id"])
            await asyncio.to_thread(followup.derive, self.journal, blocked or objective)
        else:
            await self.journal.update_objective(
                objective["id"], status="OPEN",
                progress={"lesson": lesson, "attempts_log": log[-6:], **({"plan": plan.summary(steps)} if steps else {})},
                evidence={"judged": evidence, "contract": contract, "task_id": task_id},
                last_task_id=task_id, bump_attempts=True,
                next_action=(f"step {nxt['step']}: {nxt['do']}" if nxt else "retry with a changed approach"), note=lesson,
            )
        await self.journal.record(
            "reflection.created",
            {"objective_id": objective["id"], "expected": objective["check_spec"], "actual": evidence,
             "task_status": rep.task_status, "verdict": rep.verdict, "lesson": lesson, "attempt": attempts},
            task_id=task_id,
        )
        return await self._finish(rep)

    async def _restart_if_pending(self, rep: CycleReport) -> bool:
        """Close the self-modification loop: a release committed new code, but
        the running process still runs the old one until a restart. When idle
        and launched by syrax.py, restart cleanly into the new commit."""
        if os.getenv("SYRAX_SELF_RESTART", "1") == "0" or getattr(self.core, "busy", False):
            return False
        if self.level < 5:  # restarting into its own released code is level 5 (continuous) only
            return False
        if getattr(getattr(self.core, "quality", None), "running", False):
            return False  # never restart in the middle of a quality run
        if not LAUNCHER_PID_FILE.exists():
            return False  # not started by syrax.py (tests, a bare server): nobody would bring it back
        try:  # off the event loop: its git calls hung for 60 s+ on 2026-10-15 14:38 (stall dump) and froze SYRAX
            ident = await asyncio.to_thread(self.core.selfmodel.identity)
        except Exception:
            return False
        if not ident.get("restart_pending"):
            return False
        await self.journal.record("restart.requested", {"running": ident.get("version"), "on_disk": ident.get("newer_on_disk_not_running")})
        spawn_restart()
        rep.outcome, rep.reason = "RESTARTING", f"new code on disk ({ident.get('newer_on_disk_not_running')}); restarting into it"
        return True

    async def _measure_quality(self, objective: dict, rep: CycleReport) -> bool:
        """Verify step for quality objectives: after an attempt, the cycle runs
        the quality suite instead of another task. True when it measured."""
        spec = objective.get("check_spec") or {}
        runner = getattr(self.core, "quality", None)
        if spec.get("kind") not in QUALITY_KINDS or objective.get("attempts", 0) < 1 or runner is None:
            return False
        last = self.journal.quality_runs(limit=1)
        last_ts = last[0]["ts"] if last else 0.0
        if last_ts >= objective["updated"] or time.time() - last_ts < QUALITY_MEASURE_EVERY_S:
            return False  # already measured since the attempt, or measured too recently
        try:
            row = await runner.run()
        except Exception as e:
            logger.warning(f"scheduled quality run failed: {e}")
            return False
        verdict, evidence = await asyncio.to_thread(judge, self.journal, objective, None)
        verdict, contract = await asyncio.to_thread(contracts.assess, self.journal, objective, None, verdict, evidence, "measure")
        rep.outcome, rep.verdict = "RAN", verdict if verdict == "DONE" else None
        rep.reason = f"measured: quality run {row.get('id')} at {row.get('pass_rate')}%"
        if verdict == "DONE":
            await self.journal.update_objective(objective["id"], status="DONE", evidence={"judged": evidence, "contract": contract, "task_id": None},
                                                progress={"lesson": "the fix held: verified by a scheduled quality run"}, note=rep.reason)
        else:
            await self.journal.update_objective(objective["id"], status="OPEN", evidence={"judged": evidence, "task_id": None},
                                                next_action="the measured run still fails: change the approach", note=rep.reason)
        return True

    async def _finish(self, rep: CycleReport) -> CycleReport:
        after = {"STOPPED": "STOPPED", "DISABLED": "DISABLED"}.get(rep.outcome, "WAITING")
        try:
            await self._state(after, last_outcome=rep.outcome, reason=rep.reason)
        except Exception as e:  # the state row is a report, never a reason to lose the cycle
            logger.warning(f"could not record the autonomy state: {e}")
        self.reports.append(rep)
        if len(self.reports) > 200:
            self.reports = self.reports[-200:]
        if rep.outcome in ("BUSY", "DISABLED"):
            return rep  # nothing happened; a loop tick every interval must not fill the journal
        try:
            await self.journal.record("cycle.completed", rep.to_dict())
        except Exception as e:
            logger.warning(f"could not journal cycle: {e}")
        return rep

    # ——— background loop ———

    async def loop(self, max_cycles: Optional[int] = None) -> None:
        n = 0
        while max_cycles is None or n < max_cycles:
            n += 1
            try:
                rep = await self.run_once()
            except Exception as e:
                logger.exception("autonomy cycle crashed")
                rep = CycleReport(started=time.time(), outcome="SKIPPED", reason=f"crash: {e}")
                self.reports.append(rep)
            delay = {"RAN": self.interval, "IDLE": IDLE_INTERVAL_S, "NO_BRAIN": NO_BRAIN_INTERVAL_S}.get(rep.outcome, self.interval)
            await asyncio.sleep(delay)

    def start(self) -> None:
        if estop.active(self.journal):
            logger.warning("autonomy not started: the emergency stop is on")
            return
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.create_task(self.loop())

    async def stop(self) -> None:
        if self._loop_task is not None and not self._loop_task.done():
            self._loop_task.cancel()
            await asyncio.gather(self._loop_task, return_exceptions=True)
        self._loop_task = None
        if not self._cycle_running:  # a cycle started by cycle_now keeps its objective until it finishes
            await self.journal.run(self.recover_active, "loop stopped")


TRACE_IN_SYRAX = re.compile(r'File "[^"]*?(backend/syrax/[A-Za-z0-9_/]+\.py)", line (\d+)')


def auto_keywords(text: str) -> List[str]:
    from syrax.research import keywords

    return keywords(text)


def no_brain_answered(journal: Journal, task_id: str) -> bool:
    """The task failed because no brain could be reached (BrainError "All brains failed"): an outage, not an attempt."""
    for e in reversed(journal.events(task_id)):
        if e["type"] == "task.failed":
            return str(e["payload"].get("error") or "").startswith("All brains failed")
    return False


def _research_topic(error: str) -> Optional[str]:
    """A researchable topic from an error message, or None when it is not
    something the web can explain (aborts, empty errors, journal outages)."""
    err = (error or "").strip()
    if not err or err.startswith("aborted") or "journal unavailable" in err or "All brains failed" in err:
        return None
    m = re.search(r"No module named ['\"]?([\w.]+)", err)
    if m:
        return f"python module {m.group(1)}"
    m = re.search(r"([A-Za-z]+Error|Exception)[:\s]+(.{0,80})", err)
    if m:
        return f"{m.group(1)}: {m.group(2).strip()}"
    words = auto_keywords(err)
    return " ".join(words[:6]) if len(words) >= 2 else None


def _lesson(objective: dict, task: dict, verdict: str, evidence: dict) -> str:
    spec = objective.get("check_spec") or {}
    if verdict == "DONE":
        return f"objective met: {spec.get('kind')} evidence satisfied (task {task.get('status')})"
    if spec.get("kind") == "repro_proven":
        rej = evidence.get("rejected") or {}
        return (f"no proven repro yet ({rej.get('verdict') or 'nothing harvested'}): {rej.get('reason') or evidence.get('reason') or ''}")[:300]
    if spec.get("kind") == "tool_verified":
        if not evidence.get("used_after_objective"):
            return f"the task never called `{spec.get('tool')}`; a verification objective needs the tool to actually run"
        return f"`{spec.get('tool')}` ran and failed again (last outcome {evidence.get('last_outcome')}); the same approach will not work"
    if spec.get("kind") == "human":
        return "waiting for a human decision"
    if spec.get("kind") == "quality_case_passes":
        return f"no newer quality run passes case {spec.get('case')!r}; fix, release, then run the quality suite"
    if spec.get("kind") == "quality_recovered":
        return "no newer quality run without a regression; fix, release, then run the quality suite"
    if spec.get("kind") == "benchmark_recovered":
        return f"no newer benchmark without a regression in {spec.get('metric')}; run the benchmark after fixing"
    if spec.get("kind") == "knowledge_confidence":
        return "no stronger knowledge with the same tags was stored; research more sources"
    if spec.get("kind") == "change_released":
        return "no commit was created by this objective's task: the change was never released, or the gate or review rolled it back"
    if spec.get("kind") == "file_present":
        return f"{spec.get('path')} does not exist, or was not written after the objective was set"
    if spec.get("kind") == "file_absent":
        return f"{spec.get('path')} still exists"
    if spec.get("kind") == "knowledge_stored" and evidence.get("still_disputed"):
        return (f"knowledge {evidence['still_disputed']} is still DISPUTED: `learn` the correct conclusion citing an independent "
                "primary source (not the disputed rows) at least as strong as what it contradicts, to settle it")
    if spec.get("kind") == "knowledge_stored":
        return f"nothing about {spec.get('topic')!r} was stored; research and `learn` must actually run"
    return f"task ended {task.get('status')} with error {task.get('error')!r}"
