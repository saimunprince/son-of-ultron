"""M2, a brain that finishes code: a fixed code-change benchmark.

Each case is a tiny scratch project (one or two source files and a visible
check script) and a request in plain words. The brain under test does it
through the real core and tools (kind "eval", a fresh conversation, a step
budget like a release objective's). Grading is by machine only, after the task:

  - a hidden test, written outside the workspace only at grading time and run
    in a fresh interpreter against the scratch project, must pass;
  - the visible check must be unchanged (passing by editing the check fails).

A case counts for a brain only when that brain answered most of its steps: a
requested brain that was cooling down or failed over is "not measured", never
a zero and never someone else's score. Each brain's run is journaled as
`codebench.completed`; each measured brain against the human's first brain is
an experiment, judged on pass rate. routing.preferred_for_code reads the
results, so release objectives start on the brain that finishes code best.

Runs on demand (`codebench_run` over WebSocket) and from the autonomy cycle
once a week when the service asks for it (SYRAX_CODEBENCH=1) and the human
has been quiet for a while. It costs model calls (about CASE_STEPS per case
per brain).

This file grades brains, so SYRAX's own releases may not change it (devloop.JUDGES).
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from syrax.journal import BACKEND_ROOT, Journal, JournalError

WORKSPACE = BACKEND_ROOT / "workspace" / "codebench"
CASE_STEPS = 16
CASE_TIMEOUT_S = 420.0
HIDDEN_TIMEOUT_S = 30.0
EVERY_S = 7 * 86400.0
RETRY_S = 86400.0
HUMAN_QUIET_S = 30 * 60.0
RAN, ATTEMPTED = "codebench_ran", "codebench_attempted"
WINDOW_S = 30 * 86400.0  # routing reads the benchmark runs of this window
MIN_GRADED = 4  # a brain needs this many cases it answered itself before routing trusts it
MIN_GAP = 0.25  # and must beat the human's first brain by this pass rate

PROMPT = ("Work in the folder {root} (a small Python project). {request} "
          "Check your change by running `python {check}` in that folder; it prints OK when the behaviour is right. "
          "Do not edit {check}. When it passes, reply with one line saying what you changed.")

CASES: List[Dict[str, Any]] = [
    {
        "id": "fix_word_count", "files_to_change": 1,
        "request": "word_count in textstats.py counts the empty strings between repeated spaces as words. "
                   "Fix it so words are separated by any whitespace, and an empty or blank text has 0 words.",
        "files": {
            "textstats.py": 'def word_count(text):\n    """Number of words in text."""\n    return len(text.split(" "))\n',
            "check.py": 'from textstats import word_count\n\nassert word_count("one two  three") == 3, word_count("one two  three")\nprint("OK")\n',
        },
        "check": "check.py",
        "hidden": (
            "from textstats import word_count\n"
            "assert word_count('one two  three') == 3\n"
            "assert word_count('a\\tb\\nc') == 3\n"
            "assert word_count('') == 0\n"
            "assert word_count('   ') == 0\n"
            "assert word_count('single') == 1\n"
        ),
    },
    {
        "id": "inventory_remove", "files_to_change": 1,
        "request": "Add a method remove(name, qty) to the Inventory class in inventory.py: it lowers the count of name by qty "
                   "and deletes the item when its count reaches 0; when there are fewer than qty (or none), it raises ValueError "
                   "and changes nothing.",
        "files": {
            "inventory.py": ("class Inventory:\n    def __init__(self):\n        self.items = {}\n\n"
                             "    def add(self, name, qty):\n        self.items[name] = self.items.get(name, 0) + qty\n\n"
                             "    def count(self, name):\n        return self.items.get(name, 0)\n"),
            "check.py": ("from inventory import Inventory\n\ninv = Inventory()\ninv.add('apple', 5)\ninv.remove('apple', 2)\n"
                         "assert inv.count('apple') == 3, inv.count('apple')\nprint(\"OK\")\n"),
        },
        "check": "check.py",
        "hidden": (
            "from inventory import Inventory\n"
            "inv = Inventory()\n"
            "inv.add('apple', 5)\n"
            "inv.remove('apple', 2)\n"
            "assert inv.count('apple') == 3\n"
            "inv.remove('apple', 3)\n"
            "assert 'apple' not in inv.items and inv.count('apple') == 0\n"
            "inv.add('pear', 1)\n"
            "for name, qty in (('pear', 2), ('plum', 1)):\n"
            "    try:\n"
            "        inv.remove(name, qty)\n"
            "    except ValueError:\n"
            "        pass\n"
            "    else:\n"
            "        raise AssertionError('no ValueError for ' + name)\n"
            "assert inv.items == {'pear': 1}\n"
        ),
    },
    {
        "id": "greeting_setting", "files_to_change": 2,
        "request": "Make the greeting word configurable. In config.py add a setting \"greeting\" with the default \"Hello\" to DEFAULTS. "
                   "In greet.py, greet takes an optional settings dict, greet(name=None, settings=None), whose \"greeting\" "
                   "overrides the default from config.DEFAULTS. greet() still returns \"Hello, world!\" and "
                   "greet(\"Ana\", {\"greeting\": \"Hi\"}) returns \"Hi, Ana!\".",
        "files": {
            "config.py": 'DEFAULTS = {"name": "world"}\n',
            "greet.py": ('from config import DEFAULTS\n\n\ndef greet(name=None):\n'
                         '    return "Hello, " + (name or DEFAULTS["name"]) + "!"\n'),
            "check.py": ('from greet import greet\n\nassert greet() == "Hello, world!", greet()\n'
                         'assert greet("Ana", {"greeting": "Hi"}) == "Hi, Ana!"\nprint("OK")\n'),
        },
        "check": "check.py",
        "hidden": (
            "import config\n"
            "from greet import greet\n"
            "assert config.DEFAULTS['greeting'] == 'Hello' and config.DEFAULTS['name'] == 'world'\n"
            "assert greet() == 'Hello, world!'\n"
            "assert greet('Ana', {'greeting': 'Hi'}) == 'Hi, Ana!'\n"
            "assert greet('Bo', {}) == 'Hello, Bo!'\n"
            "config.DEFAULTS['greeting'] = 'Hey'\n"
            "assert greet() == 'Hey, world!', 'greet must read the default from config.DEFAULTS'\n"
        ),
    },
    {
        "id": "rename_with_caller", "files_to_change": 2,
        "request": "Rename the function area in shapes.py to rect_area and make report.py call rect_area. "
                   "Keep area in shapes.py as an alias of rect_area so old callers still work.",
        "files": {
            "shapes.py": "def area(w, h):\n    return w * h\n",
            "report.py": "from shapes import area\n\n\ndef describe(w, h):\n    return f\"area {area(w, h)}\"\n",
            "check.py": ("from shapes import rect_area\nfrom report import describe\n\n"
                         "assert rect_area(2, 3) == 6\nassert describe(2, 3) == \"area 6\"\nprint(\"OK\")\n"),
        },
        "check": "check.py",
        "hidden": (
            "import pathlib, shapes, report\n"
            "assert shapes.rect_area(2, 3) == 6 and shapes.area(4, 5) == 20\n"
            "assert report.describe(2, 3) == 'area 6'\n"
            "src = pathlib.Path(report.__file__).read_text(encoding='utf-8')\n"
            "assert 'rect_area' in src, 'report.py must call rect_area'\n"
            "assert 'def rect_area' in pathlib.Path(shapes.__file__).read_text(encoding='utf-8')\n"
        ),
    },
]


def _digest(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def prepare(case: dict, root: Path) -> None:
    """A fresh scratch project: a leftover from an earlier run never changes the task."""
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    for name, text in case["files"].items():
        (root / name).write_bytes(text.encode("utf-8"))


def grade(case: dict, root: Path, check_digest: Optional[str]) -> List[dict]:
    """Machine checks only: the visible check is untouched and the hidden test passes."""
    now = _digest(root / case["check"])
    out = [{"check": f"{case['check']} unchanged", "ok": now is not None and now == check_digest,
            "detail": "unchanged" if now == check_digest else "edited or removed"}]
    with tempfile.TemporaryDirectory(prefix="syrax-hidden-") as d:
        test = Path(d) / "hidden_test.py"
        test.write_bytes((f"import sys\nsys.path.insert(0, {str(root)!r})\n" + case["hidden"]).encode("utf-8"))
        env = {k: v for k, v in os.environ.items() if not k.startswith("SYRAX_")}
        try:
            r = subprocess.run([sys.executable, "-I", "-B", str(test)], cwd=str(root), capture_output=True, text=True,
                               timeout=HIDDEN_TIMEOUT_S, env=env)
            ok, detail = r.returncode == 0, ((r.stderr or r.stdout).strip().splitlines() or ["passed"])[-1][:300]
        except subprocess.TimeoutExpired:
            ok, detail = False, f"hidden test ran over {HIDDEN_TIMEOUT_S:.0f}s"
    out.append({"check": "hidden test passes", "ok": ok, "detail": detail})
    return out


async def run_case(core: Any, case: dict, ws: Path = WORKSPACE, steps: int = CASE_STEPS,
                   timeout: float = CASE_TIMEOUT_S) -> dict:
    journal: Journal = core.journal
    root = Path(ws) / case["id"]
    await asyncio.to_thread(prepare, case, root)
    before = _digest(root / case["check"])
    prompt = PROMPT.format(root=root, request=case["request"], check=case["check"])
    started = time.time()
    task_id = await core.submit(prompt, said=prompt, session_id=None, kind="eval", max_steps=steps)
    if task_id is None:
        return {"id": case["id"], "ok": False, "task_id": None, "answered_by": None, "stopped": False,
                "checks": [{"check": "task started", "ok": False, "detail": "core busy"}]}
    try:
        await asyncio.wait_for(core.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        await core.cancel(f"the benchmark case ran out of time ({int(timeout)} s)")
        await core.wait()
    events = journal.events(task_id, limit=5000)
    task = journal.task(task_id) or {}
    answers = Counter(e["payload"].get("provider") for e in events
                      if e["type"] == "brain.answered" and e["payload"].get("provider"))
    checks = await asyncio.to_thread(grade, case, root, before)
    return {"id": case["id"], "files_to_change": case["files_to_change"], "ok": all(c["ok"] for c in checks),
            "task_id": task_id, "status": task.get("status"), "steps": task.get("current_step", 0),
            "ms": int((time.time() - started) * 1000), "answered_by": answers.most_common(1)[0][0] if answers else None,
            "answers": dict(answers), "checks": checks,
            # a stop from the UI (journaled by the server) ends the whole run, not just this case
            "stopped": any(e["type"] == "task.stop_requested" for e in events)}


async def measure(core: Any, brain: str, cases: Optional[List[dict]] = None, ws: Path = WORKSPACE,
                  steps: int = CASE_STEPS, timeout: float = CASE_TIMEOUT_S) -> dict:
    """Run every case with `brain` tried first. Journals `codebench.completed` and returns its payload."""
    router = getattr(core.agent, "llm", None) if core.agent is not None else None
    if router is None or not hasattr(router, "preferred"):
        raise JournalError("no brain router available")
    results: List[dict] = []
    todo = list(cases if cases is not None else CASES)
    router.preferred = brain
    try:
        for case in todo:
            results.append(await run_case(core, case, ws, steps, timeout))
            if results[-1]["stopped"]:
                break
            if len(results) == 1 and brain not in (results[0].get("answers") or {}):
                # Live 2026-10-11: groq, pollinations and ollama never answered (another brain did
                # every step), so 12 tasks spent gemini's free quota on work credited to nobody.
                break
    finally:
        router.preferred = None
    mine = [r for r in results if r["answered_by"] == brain]  # only what this brain did itself
    passed = sum(1 for r in mine if r["ok"])
    payload = {
        "brain": brain, "graded": len(mine), "passed": passed,
        "pass_rate": round(passed / len(mine), 3) if mine else None,
        "not_measured": [r["id"] for r in results if r["answered_by"] != brain],
        "never_answered": bool(results) and not any(brain in (r.get("answers") or {}) for r in results),
        "skipped": [c["id"] for c in todo[len(results):]],
        "stopped": any(r["stopped"] for r in results),
        "cases": [{k: r.get(k) for k in ("id", "files_to_change", "ok", "task_id", "status", "steps", "ms", "answered_by")}
                  | {"failed": [c["check"] + ": " + str(c["detail"])[:160] for c in r["checks"] if not c["ok"]]} for r in results],
    }
    await core.journal.record("codebench.completed", payload)
    return payload


def _verdict(a: dict, b: dict) -> tuple:
    if min(a["graded"], b["graded"]) < len(CASES) // 2:
        return "INCONCLUSIVE", (f"too few cases answered by the brain itself ({a['brain']} {a['graded']}, "
                                f"{b['brain']} {b['graded']})")
    pa, pb = a["pass_rate"], b["pass_rate"]
    if pa == pb:
        return "NO_DIFFERENCE", f"both passed {pa:.0%} of the code changes they did"
    if pb > pa:
        return "CANDIDATE_BETTER", f"{b['brain']} passed {pb:.0%} vs {a['brain']} {pa:.0%}"
    return "BASELINE_BETTER", f"{a['brain']} passed {pa:.0%} vs {b['brain']} {pb:.0%}"


async def run_all(core: Any, brains: Optional[List[str]] = None, cases: Optional[List[dict]] = None,
                  ws: Path = WORKSPACE, steps: int = CASE_STEPS, timeout: float = CASE_TIMEOUT_S,
                  now: Optional[float] = None) -> dict:
    """Measure each brain (the enabled ones, in the human's order, unless named), then
    record an experiment for each measured brain against the human's first one."""
    if core.busy:
        raise JournalError("a task is running; the code benchmark needs an idle core")
    journal: Journal = core.journal
    router = getattr(core.agent, "llm", None) if core.agent is not None else None
    if router is None or not hasattr(router, "store"):
        await core.ensure_agent()
        router = getattr(core.agent, "llm", None)
    if router is None or not hasattr(router, "store"):
        raise JournalError("no brain router available")
    order = [p for p in router.store.order if router.store.enabled(p)]
    wanted = [b for b in (brains or order) if b in order]
    if not wanted:
        raise JournalError("no enabled brain to measure")
    now = now or time.time()
    journal.set_meta(ATTEMPTED, str(now))
    runs: List[dict] = []
    skipped: Dict[str, str] = {}
    for b in wanted:
        h = getattr(router, "health", {}).get(b)
        if h is not None and getattr(h, "until", 0) > time.time():
            skipped[b] = "cooling down"
            continue
        runs.append(await measure(core, b, cases, ws, steps, timeout))
        if runs[-1]["stopped"]:
            break
    stopped = any(r["stopped"] for r in runs)
    experiments = []
    base = next((r for r in runs if r["brain"] == order[0]), None)
    if base is not None and not stopped and not base.get("never_answered"):
        for r in runs:
            if r is base or r.get("never_answered"):
                continue  # nothing was measured, so there is nothing to compare (and no row to count)
            verdict, conclusion = _verdict(base, r)
            row = await journal.run(
                journal.add_experiment_sync, f"brain {r['brain']} finishes code changes at least as well as {base['brain']}",
                {"tool": "codebench", "args": {"brain": base["brain"]}, "value": base["pass_rate"], "graded": base["graded"]},
                {"tool": "codebench", "args": {"brain": r["brain"]}, "value": r["pass_rate"], "graded": r["graded"]},
                "pass_rate", {"baseline": base["pass_rate"], "candidate": r["pass_rate"], "unit": "pass_rate",
                              "cases": [c["id"] for c in (cases or CASES)]},
                conclusion, verdict, None,
                {"CANDIDATE_BETTER": f"route code changes to {r['brain']} once it leads over {MIN_GRADED}+ own cases",
                 "BASELINE_BETTER": f"keep {base['brain']} first for code changes",
                 "NO_DIFFERENCE": "either brain", "INCONCLUSIVE": "measure again when both brains answer"}[verdict],
            )
            experiments.append(row.get("id"))
    if not stopped:
        journal.set_meta(RAN, str(now))
    return {"runs": runs, "skipped": skipped, "experiments": experiments, "stopped": stopped}


def summary(res: dict) -> str:
    parts = [f"{r['brain']} never answered" if r.get("never_answered") else
             f"{r['brain']} {r['passed']}/{r['graded']}" + (f" ({len(r['not_measured'])} not its own)" if r["not_measured"] else "")
             for r in res.get("runs") or []]
    parts += [f"{b} skipped ({why})" for b, why in (res.get("skipped") or {}).items()]
    return ", ".join(parts) + (" · stopped by the human" if res.get("stopped") else "")


def _since(journal: Journal, key: str, now: float) -> float:
    try:
        return now - float(journal.get_meta(key) or 0)
    except ValueError:
        return now


def human_quiet(journal: Journal, now: float, quiet_s: float = HUMAN_QUIET_S) -> bool:
    """The benchmark keeps the core busy for a long while: only when the human has not talked lately."""
    for t in journal.tasks(limit=50):
        if t.get("kind") == "conversation":
            return now - float(t.get("updated") or t.get("created") or 0) >= quiet_s
    return True


def due(journal: Journal, now: Optional[float] = None) -> bool:
    now = now or time.time()
    return (_since(journal, RAN, now) >= EVERY_S and _since(journal, ATTEMPTED, now) >= RETRY_S
            and human_quiet(journal, now))


def table(journal: Journal, now: Optional[float] = None, window_s: float = WINDOW_S) -> Dict[str, dict]:
    """{brain: {graded, passed, pass_rate}} over the benchmark runs of the window,
    counting only the cases each brain answered itself."""
    now = now or time.time()
    out: Dict[str, dict] = {}
    for ev in journal.events_of_type("codebench.completed", since=now - window_s):
        p = ev["payload"]
        st = out.setdefault(p.get("brain") or "?", {"graded": 0, "passed": 0})
        st["graded"] += int(p.get("graded") or 0)
        st["passed"] += int(p.get("passed") or 0)
    for st in out.values():
        st["pass_rate"] = round(st["passed"] / st["graded"], 3) if st["graded"] else None
    return out
