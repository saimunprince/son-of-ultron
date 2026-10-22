"""Repro proofs: a change to SYRAX lands with a NEW test that judge code proved fails before it.

Measured 2026-10-19: of 302 objectives, 243 were DONE, and only the 23 that came from a human's brief changed
the code; SYRAX's own objectives closed on stored knowledge or one tool call. The human's briefs landed because
each carried a test that had been run on a clean tree of HEAD and seen to FAIL before the brief was filed, and
was then checked, after the release, against what was committed. This module does those checks, so that no
model's words decide them:

- ``screen`` refuses a test that could not prove anything: not a new backend/syrax/test_*.py, nothing asserted
  (or only a constant), no import of the SYRAX code it is about, a secret-shaped literal, code above WRITE
  (a shell, the network, deletes), or a brief that would change a judge.
- ``prove`` runs it with pytest in a throwaway worktree of the base commit, outside the running tree, under the
  python_execute guard, with a secret-free config: RED (assertions failed, twice the same), RED_ERROR (only
  errors, e.g. the import of a name the change adds), NOT_RED or INVALID; with a fix diff, PROVEN (the test and
  the tests that import the changed modules pass), NOT_FIXED, CONTRACT (an existing test pins the old
  behaviour) or FIX_DOES_NOT_APPLY.
- ``file_brief`` files the change_released objective: the verbatim test, its sha256 and the proof go in its
  check, so the release and the judge can hold the landing to exactly that test.
- ``release_problems`` (DevLoop.inspect, own work) refuses a release whose test is missing, changed or no
  longer fails on the task's base, or that changes files outside the brief.
- ``fidelity`` (the change_released judge) checks the committed test byte for byte.

In devloop.JUDGES: SYRAX may not change what decides its own proofs.
Command line (read-only, no journal): ``python -m syrax.repro --check TEST --as backend/syrax/test_x.py
[--files backend/syrax/x.py ...] [--fix DIFF]`` and ``python -m syrax.repro --replay <commit>``, which proves
the test a commit added against the commit's parent, with the rest of the commit as the fix.
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from syrax.devloop import JUDGES, REPO_ROOT, _git, _test_functions, remove_worktree

TEST_PATH = re.compile(r"^backend/syrax/test_[a-z0-9_]+\.py$")
FIX_PATH = re.compile(r"^backend/syrax/[a-z0-9_]+\.py$")
SECRET_FREE_CONFIG = "backend/config/config.syrax.example.toml"
MAX_TEST_CHARS = 8000
RED_TIMEOUT_S = 300.0
GREEN_TIMEOUT_S = 900.0
GREEN_MAX_FILES = 24
ACCEPT_WITHOUT_FIX = ("RED", "RED_ERROR")
ACCEPT_WITH_FIX = ("PROVEN",)


def norm_text(text: Any) -> str:
    """Test text as it is filed, written and hashed: UTF-8, LF line endings, one final newline."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    return text.rstrip("\n") + "\n"


def test_sha(text: Any) -> str:
    return hashlib.sha256(norm_text(text).encode("utf-8")).hexdigest()


def _git_bytes(args: Sequence[str], cwd: Path, stdin: Optional[bytes] = None, timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), input=stdin, capture_output=True, timeout=timeout)


def resolve(root: Path, ref: str = "HEAD") -> str:
    r = _git(["rev-parse", "--verify", f"{ref}^{{commit}}"], root)
    sha = (r.stdout or "").strip()
    if r.returncode != 0 or not sha:
        raise ValueError(f"cannot resolve {ref!r}: {(r.stderr or '').strip()[:200]}")
    return sha


def exists_at(root: Path, sha: str, rel: str) -> bool:
    return _git(["cat-file", "-e", f"{sha}:{rel}"], root).returncode == 0


def module_of(path: str) -> Optional[str]:
    """backend/syrax/agent.py -> agent."""
    m = re.match(r"^backend/syrax/([a-z0-9_]+)\.py$", path or "")
    return m.group(1) if m else None


def imported_modules(tree: ast.AST) -> set:
    """The syrax modules a test imports, test helpers and conftest excluded."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split(".")
            if parts[0] != "syrax":
                continue
            if len(parts) >= 2:
                out.add(parts[1])
            else:
                out |= {a.name for a in node.names}
        elif isinstance(node, ast.Import):
            for a in node.names:
                parts = a.name.split(".")
                if parts[0] == "syrax" and len(parts) >= 2:
                    out.add(parts[1])
    return {m for m in out if not m.startswith("test_") and m != "conftest"}


def _test_defs(tree: ast.AST) -> list:
    fns = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef) and n.name.startswith("Test")):
        fns += [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return [f for f in fns if f.name.startswith("test")]


def _only_constant_asserts(fn: ast.AST) -> bool:
    """`assert False` fails on any tree: it proves nothing about the code."""
    asserts = [n for n in ast.walk(fn) if isinstance(n, ast.Assert)]
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
    return bool(asserts) and not calls and all(isinstance(a.test, ast.Constant) for a in asserts)


def pseudo_diff(rel: str, text: str) -> str:
    return "+++ b/" + rel + "\n" + "\n".join("+" + ln for ln in norm_text(text).splitlines()) + "\n"


def screen(test_rel: str, text: str, files: Iterable[str] = (), root: Optional[Path] = None, base: Optional[str] = None) -> List[str]:
    """What makes this test unable to prove a change to these files. Empty when it may be run."""
    from syrax import permissions
    from syrax.verify import scan_diff_text

    problems: List[str] = []
    text = norm_text(text)
    if not TEST_PATH.match(test_rel or ""):
        problems.append(f"{test_rel!r}: a repro test is a new file named backend/syrax/test_<topic>.py")
    if len(text) > MAX_TEST_CHARS:
        problems.append(f"the test has {len(text)} characters; keep it under {MAX_TEST_CHARS}")
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return problems + [f"the test does not parse: line {e.lineno}: {e.msg}"]
    found = _test_functions(text) or {}
    if not found:
        problems.append("the test has no test function")
    problems += [f"{name} asserts nothing" for name, ok in found.items() if not ok]
    problems += [f"{fn.name} asserts only a constant: it would fail on any tree" for fn in _test_defs(tree) if _only_constant_asserts(fn)]
    imported = imported_modules(tree)
    if not imported:
        problems.append("the test must import the SYRAX code it proves (from syrax.<module> import ...)")
    fixes = [f for f in files if f != test_rel]
    for f in fixes:
        if f in JUDGES:
            problems.append(f"{f}: this file judges SYRAX's own work; only a human changes it")
        elif not FIX_PATH.match(f) or f.rsplit("/", 1)[-1].startswith("test_") or f.endswith("/conftest.py"):
            problems.append(f"{f}: a brief changes modules in backend/syrax (not tests, not conftest.py)")
    wanted = {module_of(f) for f in fixes} - {None}
    if wanted and imported and not (wanted & imported):
        problems.append(f"the test imports {', '.join(sorted(imported))} but the brief changes {', '.join(sorted(wanted))}: "
                        "test the code the change is for")
    problems += scan_diff_text(pseudo_diff(test_rel, text))
    level, why, _ = permissions.level_of_source(text)
    if permissions.ORDER.index(level) > permissions.ORDER.index(permissions.WRITE):
        problems.append(f"the test {why} ({level}); a repro test reads and writes files under tmp_path only "
                        "(syrax.test_devloop's repo and git helpers make a throwaway git repository)")
    if root is not None and base and TEST_PATH.match(test_rel or "") and exists_at(Path(root), base, test_rel):
        problems.append(f"{test_rel} already exists at {base[:7]}: existing tests are the contract; name a new file")
    return problems


def _guard_paths(live_root: Path) -> List[str]:
    from syrax import guard

    live = Path(live_root).resolve()
    rules = [f"{live}{os.sep}*", f"!{live / 'backend' / 'workspace'}{os.sep}*", f"!{live / '.syrax'}{os.sep}*"]
    try:
        base = [p for p in guard.protected_paths() if not p.startswith(("!", str(live) + os.sep + "*"))]
    except Exception:
        base = []
    return list(dict.fromkeys(base + rules))


def proof_env(live_root: Path, wt: Path, guard: bool = False) -> Dict[str, str]:
    """The pytest gate's own test settings, no bytecode. With ``guard``, the python_execute guard keeps the
    journal, the keys and the running tree read-only for the code under proof. It is off by default, like in the
    gate: the replay of 2026-10-22 showed the guard turns tests that start guarded children of their own
    (test_bridge, test_guard_isolation) red, so a right change read as CONTRACT. What a test may do is screened
    before it runs (``screen``: nothing above WRITE)."""
    env = {
        "OPENMANUS_DISABLE_BROWSER_USE": "1", "SYRAX_DISABLE_WHISPER_WARMUP": "1", "SYRAX_BROWSER": "0",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "COLUMNS": "200",
    }
    if guard:
        pp = os.environ.get("PYTHONPATH", "")
        env["SYRAX_GUARD_PATHS"] = os.pathsep.join(_guard_paths(live_root))
        env["PYTHONPATH"] = str(wt / "backend" / "syrax" / "_guard_site") + (os.pathsep + pp if pp else "")
    return env


def _parse_junit(xml: Path) -> Optional[Dict[str, Any]]:
    try:
        root = ET.parse(xml).getroot()
    except (OSError, ET.ParseError):
        return None
    out: Dict[str, Any] = {"tests": 0, "passed": [], "failed": [], "errors": [], "skipped": []}
    for tc in root.iter("testcase"):
        tid = f"{tc.get('classname') or ''}::{tc.get('name') or ''}"
        out["tests"] += 1
        if tc.find("failure") is not None:
            out["failed"].append(tid)
        elif tc.find("error") is not None:
            out["errors"].append(tid)
        elif tc.find("skipped") is not None:
            out["skipped"].append(tid)
        else:
            out["passed"].append(tid)
    return out


def run_pytest(live_root: Path, wt: Path, rels: Sequence[str], timeout: float, cancel: Optional[threading.Event] = None) -> Dict[str, Any]:
    """pytest on repository paths in the worktree; per-test outcomes from its JUnit report (no -x: every test
    gets a verdict)."""
    from syrax.verify import Gate, run_gate, venv_python

    xml = wt.parent / f"junit-{len(list(wt.parent.glob('junit-*.xml')))}.xml"
    backend_rels = [r[len("backend/"):] if r.startswith("backend/") else r for r in rels]
    gate = Gate("repro", [venv_python(), "-m", "pytest", *backend_rels, "-q", "-rA", "-p", "no:cacheprovider",
                          "-o", "faulthandler_timeout=120", f"--junitxml={xml}"],
                cwd=wt / "backend", env=proof_env(live_root, wt), timeout=timeout, drop_env_prefixes=("SYRAX_",))
    res = run_gate(gate, cancel)
    parsed = _parse_junit(xml) or {"tests": 0, "passed": [], "failed": [], "errors": [], "skipped": []}
    return {**parsed, "status": res.status, "exit": res.exit_code, "ms": res.duration_ms, "tail": (res.evidence or "")[-1500:]}


def _summary(run: Dict[str, Any]) -> str:
    parts = [f"{len(run['failed'])} failed", f"{len(run['errors'])} errors", f"{len(run['passed'])} passed"]
    first = (run["failed"] + run["errors"])[:2]
    return ", ".join(parts) + (f" ({'; '.join(first)})" if first else "") + (f" [{run['status']}]" if run["status"] == "NOT_VERIFIED" else "")


def importing_tests(wt: Path, modules: Iterable[str], first: str, cap: int = GREEN_MAX_FILES) -> List[str]:
    """The proof's own test first, then the tests that import a changed module (judge-owned, so a release of
    selfedit cannot shrink what the proof runs)."""
    out = [first]
    for m in sorted(set(modules)):
        rx = re.compile(rf"(?m)^\s*(?:from\s+syrax\.{re.escape(m)}\s+import|from\s+syrax\s+import\s+[^\n]*\b{re.escape(m)}\b|import\s+syrax\.{re.escape(m)}\b)")
        for p in sorted((wt / "backend" / "syrax").glob("test_*.py")):
            rel = f"backend/syrax/{p.name}"
            if rel in out:
                continue
            try:
                if rx.search(p.read_text(encoding="utf-8", errors="replace")):
                    out.append(rel)
            except OSError:
                continue
    return out[:cap]


def changed_by(diff: str) -> List[str]:
    paths = []
    for ln in norm_text(diff).splitlines():
        m = re.match(r"^\+\+\+ (?:b/)?(\S+)", ln)
        if m and m.group(1) != "/dev/null" and m.group(1) not in paths:
            paths.append(m.group(1))
    return paths


def sweep(live_root: Path, max_age_s: float = 3600.0) -> int:
    """Remove proof worktrees a killed proof left behind (older than ``max_age_s``)."""
    import time

    gone = 0
    for d in Path(tempfile.gettempdir()).glob("syrax-repro-*"):
        try:
            if time.time() - d.stat().st_mtime < max_age_s:
                continue
        except OSError:
            continue
        if (d / "wt").exists():
            remove_worktree(d / "wt", live_root)
        shutil.rmtree(d, ignore_errors=True)
        gone += 1
    if gone:
        _git(["worktree", "prune"], live_root)
    return gone


def prove(live_root: Path, test_rel: str, test_text: str, fix_diff: Optional[str] = None, base: str = "HEAD",
          cancel: Optional[threading.Event] = None, red_runs: int = 2) -> Dict[str, Any]:
    """Run the test on a clean worktree of ``base`` (and, with ``fix_diff``, again after the fix)."""
    live_root = Path(live_root)
    sweep(live_root)
    sha = resolve(live_root, base)
    text = norm_text(test_text)
    out: Dict[str, Any] = {"test": test_rel, "sha256": test_sha(text), "base": sha}
    tmp = Path(tempfile.mkdtemp(prefix="syrax-repro-"))
    wt = tmp / "wt"
    try:
        add = _git(["worktree", "add", "--detach", str(wt), sha], live_root)
        if add.returncode != 0:
            return {**out, "verdict": "INVALID", "reason": f"git worktree add failed: {(add.stderr or '').strip()[:200]}"}
        config, example = wt / "backend" / "config" / "config.toml", wt / SECRET_FREE_CONFIG
        if example.is_file() and not config.exists():
            shutil.copyfile(example, config)  # a checkout needs a config to import app.*; never the one with keys
        target = wt / test_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))
        runs = [run_pytest(live_root, wt, [test_rel], RED_TIMEOUT_S, cancel)]
        if runs[0]["failed"] and red_runs > 1:
            runs.append(run_pytest(live_root, wt, [test_rel], RED_TIMEOUT_S, cancel))
        first = runs[0]
        out["red"] = {"summary": _summary(first), "failed": first["failed"], "errors": first["errors"], "tail": first["tail"][-600:]}
        if first["status"] == "NOT_VERIFIED" or first["tests"] == 0 or not (first["failed"] or first["errors"] or first["passed"]):
            return {**out, "verdict": "INVALID", "reason": "no test ran: " + (first["tail"].strip().splitlines() or ["no output"])[-1][:200]}
        if first["failed"]:
            if len(runs) > 1 and sorted(runs[1]["failed"]) != sorted(first["failed"]):
                return {**out, "verdict": "INVALID", "reason": "the failures changed between two runs: the test is not deterministic"}
            verdict = "RED"
        elif first["errors"]:
            verdict = "RED_ERROR"
        else:
            return {**out, "verdict": "NOT_RED", "reason": f"the test passes on {sha[:7]}: it does not see the bug"}
        out["verdict"] = verdict
        if not fix_diff:
            return out
        diff = norm_text(fix_diff)
        touched = changed_by(diff)
        if test_rel in touched:
            return {**out, "verdict": "INVALID", "reason": "the fix must not change the test"}
        applied = _git_bytes(["apply", "--whitespace=nowarn", "--recount", "-"], wt, stdin=diff.encode("utf-8"))
        if applied.returncode != 0:
            return {**out, "verdict": "FIX_DOES_NOT_APPLY", "reason": (applied.stderr or b"").decode("utf-8", "replace").strip()[:300]}
        mods = [m for m in (module_of(p) for p in touched) if m]
        tests = importing_tests(wt, mods, test_rel)
        green = run_pytest(live_root, wt, tests, GREEN_TIMEOUT_S, cancel)
        own = [t for t in green["failed"] + green["errors"] if t.split("::")[0].endswith(Path(test_rel).stem)]
        others = [t for t in green["failed"] + green["errors"] if t not in own]
        out["green"] = {"summary": _summary(green), "ran": tests, "failed": green["failed"], "errors": green["errors"]}
        if green["status"] == "NOT_VERIFIED":
            out["verdict"], out["reason"] = "INVALID", "the run after the fix did not finish: " + green["tail"][-200:]
        elif own:
            out["verdict"], out["reason"] = "NOT_FIXED", f"the test still fails after the fix: {'; '.join(own[:3])}"
        elif others:
            out["verdict"], out["reason"] = "CONTRACT", ("existing tests fail after the fix (they pin the old behaviour; a human "
                                                         f"decides): {'; '.join(others[:5])}")
        else:
            out["verdict"] = "PROVEN"
        return out
    finally:
        remove_worktree(wt, live_root)
        shutil.rmtree(tmp, ignore_errors=True)


def compact(proof: Dict[str, Any]) -> Dict[str, Any]:
    """The proof as it travels in objectives and replies."""
    keep = {"verdict": proof.get("verdict"), "test": proof.get("test"), "base": str(proof.get("base") or "")[:12],
            "sha256": proof.get("sha256"), "red": (proof.get("red") or {}).get("summary")}
    if proof.get("green"):
        keep["green"] = proof["green"].get("summary")
    if proof.get("reason"):
        keep["reason"] = str(proof["reason"])[:300]
    return keep


def brief_goal(goal: str, test_rel: str, text: str, files: Sequence[str], proof: Dict[str, Any]) -> str:
    fixes = [f for f in files if f != test_rel]
    return (
        f"{goal.strip()}\n\nRepro, proven by the judge (not by a model): {test_rel} fails on {str(proof['base'])[:7]} "
        f"({(proof.get('red') or {}).get('summary', '')}). It is already in your worktree exactly as filed "
        f"(sha256 {proof['sha256'][:12]}); if it is missing, create it with exactly the content below. Do not change it: "
        f"a release with a different test is refused. Change only: {', '.join(fixes) or 'the code it tests'}. "
        "Then `release`: the release proves the test still fails on your base, and the gate proves it passes.\n\n"
        f"The test, verbatim:\n{norm_text(text)}"
    )


def file_brief(journal, goal: str, reason: Optional[str], test_rel: str, text: str, files: Sequence[str],
               proof: Dict[str, Any], priority: int = 1, source: str = "human", origin: Optional[dict] = None) -> Optional[dict]:
    """The change_released objective a proven test becomes. None when the same test was filed before."""
    text = norm_text(text)
    sha = test_sha(text)
    all_files = sorted(set(files) | {test_rel})
    check = {"kind": "change_released", "files": all_files,
             "repro": {"test": test_rel, "sha256": sha, "base": proof["base"], "verdict": proof["verdict"], "text": text}}
    evidence = {"repro": {k: v for k, v in compact(proof).items() if k != "sha256"}, **({"origin": origin} if origin else {})}
    return journal.add_objective_sync(brief_goal(goal, test_rel, text, all_files, proof), reason, priority, source, check,
                                      key=f"repro-brief:{sha[:16]}", evidence=evidence)


def release_problems(task_root: Path, live_root: Path, files: Dict[str, str], objective: Optional[dict],
                     cancel: Optional[threading.Event] = None) -> List[str]:
    """For a release of a brief that carries a repro: the filed test, byte for byte, as a new file; nothing
    outside the brief; and the test still fails on the base the task started from."""
    spec = (objective or {}).get("check_spec") or {}
    rp = spec.get("repro") if isinstance(spec.get("repro"), dict) else None
    if not rp or not rp.get("test"):
        return []
    test = rp["test"]
    problems: List[str] = []
    if test not in files:
        problems.append(f"{test} is not in this release: it is the brief's repro test; create it exactly as filed (the brief "
                        "holds it) and fix the code so it passes")
    elif files[test] != "??":
        problems.append(f"{test} must be a new file")
    else:
        try:
            body = (Path(task_root) / test).read_bytes()
        except OSError as e:
            body = b""
            problems.append(f"{test} cannot be read: {e}")
        if body and test_sha(body) != rp.get("sha256"):
            problems.append(f"{test} differs from the filed test (sha256 {str(rp.get('sha256'))[:12]}): restore it exactly as "
                            "filed and change the code instead; the test is the proof, not the patient")
    allowed = set(spec.get("files") or []) | {test}
    extra = sorted(f for f in files if f not in allowed)
    if extra:
        problems.append(f"this brief may change only {', '.join(sorted(allowed))}; {', '.join(extra)} is outside it. If the fix "
                        "needs another file, say which and why in your final answer instead")
    if problems:
        return problems
    base = _git(["rev-parse", "HEAD"], Path(task_root)).stdout.strip() or "HEAD"
    again = prove(live_root, test, (Path(task_root) / test).read_bytes().decode("utf-8", "replace"), base=base, cancel=cancel, red_runs=1)
    if again.get("verdict") not in ACCEPT_WITHOUT_FIX:
        return [f"the filed test no longer fails on {base[:7]} ({again.get('verdict')}: {again.get('reason') or ''}): the "
                "behaviour it was filed for is gone; nothing to release for this brief"]
    return []


def fidelity(root: Path, commits: Sequence[str], rp: Dict[str, Any]) -> Dict[str, Any]:
    """The committed test equals the filed one (sha256 of its LF text), in the newest commit that holds it."""
    for c in reversed(list(commits)):
        if not c:
            continue
        r = _git(["show", f"{c}:{rp.get('test')}"], Path(root))
        if r.returncode == 0:
            sha = test_sha(r.stdout or "")
            return {"ok": sha == rp.get("sha256"), "commit": str(c)[:12], "sha256": sha[:12]}
    return {"ok": False, "reason": f"no commit of this objective holds {rp.get('test')}"}


def replay(root: Path, commit: str) -> Dict[str, Any]:
    """Prove the test a commit added against its parent, with the rest of the commit as the fix: the judge's
    verdict on a change that is known to be right (acceptance for this module)."""
    root = Path(root)
    sha = resolve(root, commit)
    names = _git(["diff", "--name-status", f"{sha}^", sha], root).stdout.splitlines()
    added = [ln.split("\t")[-1] for ln in names if ln.startswith("A\t") and TEST_PATH.match(ln.split("\t")[-1])]
    if not added:
        return {"commit": sha[:7], "verdict": "SKIPPED", "reason": "the commit adds no backend/syrax test"}
    test = added[0]
    text = _git(["show", f"{sha}:{test}"], root).stdout
    others = [ln.split("\t")[-1] for ln in names if ln.split("\t")[-1] != test]
    fix = _git(["diff", f"{sha}^", sha, "--", *others], root).stdout if others else ""
    proof = prove(root, test, text, fix_diff=fix or None, base=f"{sha}^")
    return {"commit": sha[:7], "test": test, "files": others, **compact(proof)}


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    import json
    import sys

    p = argparse.ArgumentParser(prog="python -m syrax.repro", description=__doc__.split("\n\n")[0])
    p.add_argument("--replay", nargs="*", metavar="COMMIT", help="prove the tests these commits added against their parents")
    p.add_argument("--check", metavar="TEST_FILE", help="a test file to screen and prove")
    p.add_argument("--as", dest="rel", metavar="REPO_PATH", help="where the test goes, e.g. backend/syrax/test_x.py")
    p.add_argument("--files", nargs="*", default=[], help="the modules the brief changes")
    p.add_argument("--fix", metavar="DIFF_FILE", help="a unified diff of the intended change")
    p.add_argument("--base", default="HEAD")
    p.add_argument("--root", default=str(REPO_ROOT))
    a = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    root = Path(a.root)
    if a.replay is not None:
        bad = 0
        for c in a.replay:
            r = replay(root, c)
            bad += r.get("verdict") not in ("PROVEN", "SKIPPED")
            print(json.dumps(r, ensure_ascii=False))
        return 1 if bad else 0
    if not a.check or not a.rel:
        p.error("--check TEST_FILE --as backend/syrax/test_<topic>.py, or --replay COMMIT...")
    text = Path(a.check).read_text(encoding="utf-8")
    base = resolve(root, a.base)
    problems = screen(a.rel, text, a.files, root, base)
    if problems:
        print(json.dumps({"verdict": "REFUSED", "problems": problems}, ensure_ascii=False))
        return 1
    fix = Path(a.fix).read_text(encoding="utf-8") if a.fix else None
    proof = prove(root, a.rel, text, fix_diff=fix, base=base)
    print(json.dumps(compact(proof), ensure_ascii=False))
    return 0 if proof["verdict"] in (ACCEPT_WITH_FIX if fix else ACCEPT_WITHOUT_FIX) else 1


if __name__ == "__main__":
    raise SystemExit(main())
