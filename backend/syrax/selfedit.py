"""Phase 3 of the self-improvement plan: SYRAX changes its own code the way an
engineer does, with a map and a patch, not by overwriting files blind.

repo_map   read-only: the system map's components with their code and tests, and
           an index of the backend modules (lines, first docstring line), filtered
           by a query. The map is docs/system_map.json; the index is read from
           the tree the task works in (its worktree when isolated).
apply_patch a unified diff applied with `git apply` to that tree; then every
           touched .py file is compiled and the tests the system map says cover
           the touched files run (pytest, bounded). The report says what was
           applied, what ran and what failed; a failed patch applies nothing.
           When git cannot place the hunks, each one's old-side lines are looked
           for in the file and placed where they occur exactly once (plan 3,
           2026-10-25); the report then says APPLIED BY CONTENT.
           Protected files (devloop.JUDGES) are refused for SYRAX's own work by
           permissions.decide before this runs, and by the release gate after.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from app.tool.base import BaseTool, ToolResult
from syrax.journal import BACKEND_ROOT

REPO_ROOT = BACKEND_ROOT.parent
MODULE_DIR = "backend/syrax"
TEST_TIMEOUT_S = 300
MAX_TEST_FILES = 16
PATCH_MAX_CHARS = 200_000
_DIFF_PATH = re.compile(r"^(?:\+\+\+|---) (?:[ab]/)?(\S+)", re.M)


def work_root() -> Path:
    """The tree the current task edits: its worktree when the task is isolated (editor.ROOT_MAP),
    else the running repository."""
    from syrax import editor

    return Path(editor.ROOT_MAP[1]) if editor.ROOT_MAP else REPO_ROOT


def system_map(root: Path) -> dict:
    try:
        return json.loads((root / "docs" / "system_map.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"components": []}


def _first_doc_line(path: Path) -> str:
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:2000]
    except OSError:
        return ""
    m = re.search(r'^\s*(?:r|u)?"""\s*(.+?)\s*$', head, re.M)
    return (m.group(1) if m else "").strip('"').strip()[:110]


def module_index(root: Path, query: str = "") -> List[Dict[str, Any]]:
    """backend/syrax modules (tests apart) with line counts and their first docstring line."""
    q = query.lower()
    out = []
    for p in sorted((root / MODULE_DIR).glob("*.py")):
        if p.name.startswith("test_") or p.name == "__init__.py":
            continue
        rel = f"{MODULE_DIR}/{p.name}"
        doc = _first_doc_line(p)
        if q and q not in rel.lower() and q not in doc.lower():
            continue
        try:
            lines = sum(1 for _ in p.open("rb"))
        except OSError:
            lines = 0
        out.append({"path": rel, "lines": lines, "doc": doc, "test": f"{MODULE_DIR}/test_{p.stem}.py" if (root / MODULE_DIR / f"test_{p.stem}.py").is_file() else None})
    return out


def components_for(root: Path, query: str = "") -> List[Dict[str, Any]]:
    q = query.lower()
    out = []
    for c in system_map(root).get("components", []):
        name = str(c.get("component") or "")
        code = [str(x).split(" ")[0] for x in c.get("code") or []]
        tests = [str(t).split(" ")[0] for t in c.get("tests") or []]
        blob = " ".join([name, str(c.get("purpose") or ""), *code]).lower()
        if q and q not in blob:
            continue
        out.append({"component": name, "purpose": str(c.get("purpose") or "")[:140], "code": code, "tests": tests,
                    "limitations": [str(x)[:120] for x in (c.get("limitations") or [])][:3]})
    return out


def render_map(root: Path, query: str = "") -> str:
    comps, mods = components_for(root, query), module_index(root, query)
    lines = [f"repo map of {root}" + (f" for {query!r}" if query else "") + f": {len(comps)} components, {len(mods)} modules"]
    for c in comps[:12]:
        lines.append(f"\n[{c['component']}] {c['purpose']}")
        lines.append("  code:  " + ", ".join(c["code"][:8]) + (" …" if len(c["code"]) > 8 else ""))
        if c["tests"]:
            lines.append("  tests: " + ", ".join(c["tests"][:6]) + (" …" if len(c["tests"]) > 6 else ""))
        for lim in c["limitations"]:
            lines.append(f"  limit: {lim}")
    if comps[12:]:
        lines.append(f"\n… and {len(comps) - 12} more components; narrow the query")
    if mods:
        lines.append("\nmodules:")
        for m in mods[:40]:
            lines.append(f"  {m['path']:<36} {m['lines']:>5} lines  {m['doc']}" + (f"  (tests: {m['test']})" if m["test"] else "  (no test file)"))
        if mods[40:]:
            lines.append(f"  … and {len(mods) - 40} more; narrow the query")
    named = [f for f in file_matches(root, query) if f not in {m["path"] for m in mods}]
    if named:
        lines.append("\nfiles whose path matches (repository-relative, as apply_patch wants them):")
        lines += [f"  {f}" for f in named[:15]] + ([f"  … and {len(named) - 15} more; narrow the query"] if named[15:] else [])
    # quality case self_map_protected, 2026-10-31: the line named only "devloop.JUDGES", and with test files called
    # test_judge_*.py in the matches the brain answered with those. The judges are named, by file name.
    from syrax.devloop import JUDGES

    names = sorted({Path(j).name for j in JUDGES})
    lines.append("\nProtected (never patched by SYRAX; a human commits those), the judges in devloop.JUDGES: " + ", ".join(names) + ".")
    return "\n".join(lines)


def file_matches(root: Path, query: str) -> List[str]:
    """Tracked files whose path contains the query (case-insensitive). Live 2026-10-17 (quality run #46,
    self_patch_docs): "EXECUTION_PLAN" matched no component or module, so the brain went looking with python from
    backend/, wrote "../docs/EXECUTION_PLAN.md" into the diff, and apply_patch refused the path."""
    q = (query or "").strip().lower()
    if len(q) < 3:
        return []
    out = _git(["ls-files"], root)
    return [f for f in out.stdout.splitlines() if q in f.lower() and "node_modules/" not in f]


# ——— the patch ———

def normalize_headers(diff: str) -> str:
    """Live 2026-10-14 (quality run #39, self_patch_no_test): a brain wrote `+++ backend/syrax/x.py`
    without the b/ prefix; `git apply` strips the first path component regardless (-p1), so it wrote
    `syrax/x.py` at the repository root while the journal, the rollback and the permission check all
    read `backend/syrax/x.py`. A header without a/ or b/ now gets one, so git strips exactly that."""
    out = []
    for line in diff.split("\n"):
        for marker, prefix in (("--- ", "a/"), ("+++ ", "b/")):
            if line.startswith(marker):
                rest = line[len(marker):]
                token = rest.split("\t", 1)[0].strip()
                if token and token != "/dev/null" and not token.startswith(("a/", "b/")):
                    line = marker + prefix + rest.lstrip()
                break
        out.append(line)
    return "\n".join(out)


_EXT_HEADER = ("diff --git ", "index ", "new file mode", "deleted file mode", "old mode", "new mode", "similarity index",
               "dissimilarity index", "rename from", "rename to", "copy from", "copy to")


def file_sections(diff: str) -> List[str]:
    """A unified diff split into one diff per file. A section starts at its '--- ' line followed by '+++ ', or at the
    git header lines just above it (diff --git, new file mode, index ...). Live 2026-10-15 (objective 266): a git-style
    diff left the next file's "diff --git ... new file mode" lines at the end of the section before; applied alone,
    that section created the new file empty, and the new file's own section then failed with "already exists"."""
    lines = diff.split("\n")
    starts = []
    for i in range(len(lines) - 1):
        if lines[i].startswith("--- ") and lines[i + 1].startswith("+++ "):
            s = i
            while s > (starts[-1] if starts else -1) + 1 and lines[s - 1].startswith(_EXT_HEADER):
                s -= 1
            starts.append(s)
    if not starts:
        return [diff]
    out = []
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else len(lines)
        part = "\n".join(lines[s:e]).rstrip("\n") + "\n"
        out.append(part)
    return out


def diff_paths(diff: str) -> List[str]:
    """Repository-relative paths a unified diff touches (a/ and b/ prefixes stripped, /dev/null dropped)."""
    seen: List[str] = []
    for m in _DIFF_PATH.finditer(diff):
        p = m.group(1).strip()
        if p and p != "/dev/null" and p not in seen:
            seen.append(p)
    return seen


_HUNK = re.compile(r"^@@ -(\d+)", re.M)


def repo_relative(f: str, root: Path) -> Optional[str]:
    """Live 2026-10-22 (quality run #58, self_patch_docs): the brain wrote "../docs/EXECUTION_PLAN.md", a path from
    backend/ where python_execute starts, was told only that paths must be repository-relative, and answered that
    the file was out of reach. A path written from backend/, or an absolute one inside the repository (the task's
    tree or the running one), names the file it meant when that file or its folder exists."""
    if f.startswith("/") or re.match(r"^[A-Za-z]:", f):
        candidates = [(Path(f), base) for base in (root, REPO_ROOT)]
    else:
        candidates = [(start / f, root) for start in (root / "backend", root / "backend" / "syrax")]
    for path, base in candidates:
        try:
            rel = Path(os.path.normpath(path)).relative_to(Path(os.path.normpath(base)))
        except ValueError:
            continue
        if rel.parts and ".." not in rel.parts and ((root / rel).exists() or (root / rel).parent.is_dir()):
            return rel.as_posix()
    return None


def _hunk_old_side(rows: List[str], j: int) -> List[str]:
    """The ' ' and '-' lines of the hunk whose @@ header is rows[j]; an empty row is a blank context line."""
    old = []
    for k in range(j + 1, len(rows)):
        row = rows[k]
        if row.startswith("@@") or row.startswith("diff --git ") or (
                row.startswith("--- ") and k + 1 < len(rows) and rows[k + 1].startswith("+++ ")):
            break
        if row == "" or row[0] in " -":
            old.append(row[1:])
    return old


def context_hint(diff: str, root: Path, around: int = 6, tail: int = 8) -> str:
    """Live 2026-10-14 (quality run #34, self_patch_docs): the brain's hunk named line 159 of a
    217-line file with context that is not there, twice. When a patch does not apply, show what the
    file really holds around each hunk, numbered, so the next diff is made from the file, not memory.

    Live 2026-10-26 (journal, 30 days: 149 "does not apply cleanly" refusals; self_patch_docs failed 4 of 8 runs):
    asked to add a line at the end of a doc, the brain invented its content ("# Execution Plan / Initial setup.") in
    a hunk at line 1 and was shown only the head. When a hunk's context and '-' lines are nowhere in the file, its
    line number is a guess: the file's last lines are shown too (once per file), so an append is diffed from them."""
    out = []
    tailed = set()
    current = old = None
    rows = diff.split("\n")
    if rows and rows[-1] == "":
        rows.pop()
    for j, line in enumerate(rows):
        if line.startswith("--- "):
            old = line[4:].split("\t")[0].strip()
            continue
        if line.startswith("+++ "):
            m = _DIFF_PATH.match(line)
            current = m.group(1) if m else None
            continue
        h = _HUNK.match(line)
        if not h or not current:
            continue
        p = root / current
        if not p.is_file():
            out.append(f"{current}: does not exist (a new file diffs from /dev/null)")
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        if old == "/dev/null":
            # Live 2026-10-22 (quality run #58, self_patch_docs): asked to add a line at the end of an existing doc,
            # the brain diffed it from /dev/null and was shown its first lines; the end is where the change goes.
            tail = "\n".join(f"{i:>5}: {lines[i - 1]}" for i in range(max(1, len(lines) - around + 1), len(lines) + 1))
            out.append(f"{current} already exists: a diff from /dev/null only creates new files. Diff it as "
                       f"'--- a/{current}' / '+++ b/{current}' with its current lines as context; it has {len(lines)} "
                       f"lines and ends:\n{tail}")
            current = None  # one note per file
            continue
        start = int(h.group(1))
        lo, hi = max(1, start - around), min(len(lines), start + around)
        snippet = "\n".join(f"{i:>5}: {lines[i - 1]}" for i in range(lo, hi + 1))
        done = already_applied(diff, current, lines)
        if done:
            out.append(f"{current}: this hunk is ALREADY APPLIED (the file already holds: {done}). Nothing to patch; "
                       "if that was the change, the task is done.")
        out.append(f"{current} has {len(lines)} lines; around line {start}:\n{snippet}")
        side = _hunk_old_side(rows, j)
        if not done and current not in tailed and not (side and locate_block(lines, side)[0]):
            tailed.add(current)
            t_lo = max(hi + 1, len(lines) - tail + 1)  # the snippet above may already reach the end
            if t_lo <= len(lines):
                ends = "\n".join(f"{i:>5}: {lines[i - 1]}" for i in range(t_lo, len(lines) + 1))
                out.append(f"... {current} ends at line {len(lines)} (this hunk's context and '-' lines are nowhere in "
                           f"the file, so line {start} is only its @@ header's guess; to add at the end, diff against "
                           f"these last lines):\n{ends}")
    return "\n".join(out)[:3000]


def already_applied(diff: str, path: str, lines: List[str]) -> str:
    """Live 2026-10-14 (quality run #35 rerun, self_patch_edit): the brain changed the line with the
    editor, then sent the same diff fifteen times, each refused because the '-' line was gone. When
    every '+' line of a file's hunks is already in the file and no '-' line is, the change is done."""
    plus, minus, current = [], [], None
    for line in diff.split("\n"):
        if line.startswith("+++ "):
            m = _DIFF_PATH.match(line)
            current = m.group(1) if m else None
        elif current == path and line.startswith("+") and not line.startswith("+++"):
            plus.append(line[1:].rstrip())
        elif current == path and line.startswith("-") and not line.startswith("---"):
            minus.append(line[1:].rstrip())
    body = {l.rstrip() for l in lines}
    if plus and all(p in body for p in plus) and not any(m in body for m in minus if m.strip()):
        return "; ".join(p.strip() for p in plus[:3])[:160]
    return ""


def _git(args: List[str], cwd: Path, stdin: Optional[str] = None) -> subprocess.CompletedProcess:
    """git with the patch on stdin as bytes. Live 2026-10-14 (quality runs #34-#37): in text mode,
    Windows turned every \n of the patch into \r\n, so no correct diff of an LF file ever applied;
    the tests passed only because their files were written with CRLF too."""
    r = subprocess.run(["git", *args], cwd=str(cwd), input=stdin.encode("utf-8") if stdin is not None else None,
                       capture_output=True, timeout=60)
    return subprocess.CompletedProcess(r.args, r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace"))


def importing_tests(root: Path, module: str) -> List[str]:
    """Test files that import a backend/syrax module (from syrax.<m> import / from syrax import <m> / import
    syrax.<m>), the module's own test file first. Live 2026-10-14 (objective 224, attempt 4): apply_patch ran
    only test_memory.py, SYRAX released, and the gate failed on test_memory_types.py, which imports memory too."""
    rx = re.compile(rf"(?m)^\s*(?:from\s+syrax\.{re.escape(module)}\s+import|from\s+syrax\s+import\s+[^\n]*\b{re.escape(module)}\b|import\s+syrax\.{re.escape(module)}\b)")
    out = []
    for p in sorted((root / MODULE_DIR).glob("test_*.py")):
        try:
            if rx.search(p.read_text(encoding="utf-8", errors="replace")):
                out.append(f"{MODULE_DIR}/{p.name}")
        except OSError:
            continue
    own = f"{MODULE_DIR}/test_{module}.py"
    return ([own] if own in out else []) + [t for t in out if t != own]


def covering_tests(root: Path, files: List[str]) -> List[str]:
    """Test files to run after touching `files`: the system map's component tests for them, each
    module's own test_<module>.py, the other tests that import the module, and a touched test file
    itself; only files that exist, at most MAX_TEST_FILES."""
    from syrax.devloop import impact_of

    wanted: List[str] = []
    for f in files:
        p = Path(f)
        if p.name.startswith("test_") and p.suffix == ".py":
            wanted.append(f)
    for pat in impact_of({f: "M" for f in files}, root).get("component_tests", []):
        head = pat.split("::")[0]
        if head.endswith(".py"):
            mod = head if head.startswith("backend/") else f"backend/{head}"
            if mod not in wanted:
                wanted.append(mod)
        else:
            mod = head.replace(".", "/")
            tpath = f"backend/{mod}.py" if not mod.startswith("backend/") else f"{mod}.py"
            if tpath not in wanted:
                wanted.append(tpath)
    for f in files:
        p = Path(f)
        if p.suffix == ".py" and f.startswith(MODULE_DIR + "/") and not (p.name.startswith("test_")):
            wanted.append(f"{MODULE_DIR}/test_{p.stem}.py")
            wanted += importing_tests(root, p.stem)
    out: List[str] = []
    for w in wanted:
        if w not in out and (root / w).is_file():
            out.append(w)
    return out[:MAX_TEST_FILES]


def run_tests(root: Path, test_files: List[str], timeout: float = TEST_TIMEOUT_S) -> Dict[str, Any]:
    """pytest on the covering tests, from the backend of `root`, with the gate's test settings."""
    from syrax.verify import venv_python

    rel = [t[len("backend/"):] if t.startswith("backend/") else t for t in test_files]
    env = {k: v for k, v in os.environ.items() if not k.startswith("SYRAX_")}
    env.update({"OPENMANUS_DISABLE_BROWSER_USE": "1", "SYRAX_DISABLE_WHISPER_WARMUP": "1", "SYRAX_BROWSER": "0", "COLUMNS": "200"})
    from syrax import _confine

    # the covering tests may be ones SYRAX just wrote: they change files only in the tree and a private TMPDIR
    # (Linux Landlock via the running server's _confine.py; audit 2026-10-28)
    tmp = tempfile.mkdtemp(prefix="syrax_preflight_tmp_")
    env["TMPDIR"] = tmp
    cmd = _confine.wrap([venv_python(), "-m", "pytest", *rel, "-q", "-x", "--tb=short", "-p", "no:cacheprovider"], [root, tmp])
    try:
        r = subprocess.run(cmd, cwd=str(root / "backend"), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "ran": rel, "summary": f"tests did not finish in {int(timeout)} s", "tail": ""}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    out = (r.stdout or "") + (r.stderr or "")
    summary = next((ln for ln in reversed(out.splitlines()) if re.search(r"\d+ (passed|failed|error)", ln)), out.strip().splitlines()[-1] if out.strip() else "no output")
    return {"ok": r.returncode == 0, "ran": rel, "summary": summary.strip(), "tail": failure_text(out)}


_SECTION = re.compile(r"^=+ (.+?) =+$")
_NOISE = re.compile(r"^-+ Captured (stderr|stdout|log) (setup|teardown) -+$")


def failure_text(out: str, limit: int = 1500) -> str:
    """What a failing pytest run says about the failure: the FAILURES or ERRORS section and the short summary,
    without the warnings summary or the setup noise. Live 2026-10-15 (objective 232): the last 25 lines were
    deprecation warnings, so SYRAX saw "AssertionError: asse..." three attempts in a row and guessed the cause."""
    lines = out.strip().splitlines()
    keep: List[str] = []
    section, noise = "", False
    for ln in lines:
        m = _SECTION.match(ln)
        if m:
            section, noise = m.group(1).lower(), False
            if section in ("failures", "errors") or section.startswith("short test summary"):
                keep.append(ln)
            continue
        if section in ("failures", "errors"):
            if ln.startswith(("____", "----")):
                noise = bool(_NOISE.match(ln))
            if not noise:
                keep.append(ln)
        elif section.startswith("short test summary") or (keep and ln.startswith("!!")):
            keep.append(ln)
    if not keep:
        keep = lines[-25:]
    text = "\n".join(keep)
    if len(text) > limit:
        tail = text[-(limit - 120):]
        text = "\n".join(keep[:2]) + "\n...\n" + tail[tail.find("\n") + 1:]
    return text


def numstat(part: str, opts: List[str], root: Path) -> Optional[Tuple[int, int]]:
    """(added, deleted) lines of a patch as git would apply it, or None when it does not apply."""
    r = _git(["apply", "--check", "--numstat", *opts, "-"], root, stdin=part)
    if r.returncode != 0:
        return None
    added = deleted = 0
    for ln in r.stdout.splitlines():
        cols = ln.split("\t")
        if len(cols) >= 2:
            added += int(cols[0]) if cols[0].isdigit() else 0
            deleted += int(cols[1]) if cols[1].isdigit() else 0
    return added, deleted


# ——— plan 3: place hunks by their lines, not their numbers ———
# Measured 2026-10-25 (docs/AUDIT_2026-10-25.md item 5; 30 days of the journal replayed): of the 51 refused diffs
# that still fail with the two git plans, 19 apply when each hunk's old side is found in the file as one block that
# occurs exactly once, with no wrong placement and none of the ten stale probes accepted. The common case: a hunk
# with no trailing context, which git reads as "must end the file" (apply.c match_end), so `-TEST_TIMEOUT_S = 300`
# with its line above was refused 15 times. `git apply -C1`, `-C0`, `--ignore-whitespace` and `--unidiff-zero`
# put hunks in the wrong place on the same diffs; they are not used.

_HUNK_HEAD = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_NUMBERED = re.compile(r"^\s*\d+\t")  # a `cat -n` line pasted into the diff
# Live 2026-10-29 (quality self_patch_edit): the brain headed its hunk with a bare "@@", as many models write diffs; git
# found "No valid patches" and this plan found "no @@ hunks", though it never uses the numbers. A bare "@@" (or one with
# only a section title) starts a hunk here too.
_BARE_HEAD = re.compile(r"^@@(?:\s+[^-+@\s].*)?\s*$")


def parse_hunks(section: str) -> List[List[Tuple[str, str]]]:
    """One file's diff as hunks of (tag, text): ' ' context, '-' old, '+' new. An empty body line is a blank context
    line whose leading space was lost (git reads it the same way); a '\\ No newline' marker is dropped. Raises
    ValueError for a body line that is none of these (a context line without its space, `cat -n` numbering, an ed
    command such as `12a`: pasted, not diffed) and for a section without hunks."""
    hunks: List[List[Tuple[str, str]]] = []
    lines = section.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    for line in lines:
        if _HUNK_HEAD.match(line) or _BARE_HEAD.match(line):
            hunks.append([])
            continue
        if not hunks or line.startswith("\\"):
            continue  # the headers above the first hunk; "\ No newline at end of file"
        if line == "":
            tag, text = " ", ""
        elif line[0] in " -+":
            tag, text = line[0], line[1:]
        else:
            raise ValueError(f"hunk {len(hunks)} holds a line that is not a diff line: {line[:60]!r}")
        if _NUMBERED.match(text):
            raise ValueError(f"hunk {len(hunks)} holds a numbered line (`cat -n` output, not file text): {line[:60]!r}")
        hunks[-1].append((tag, text))
    if not hunks:
        raise ValueError("no @@ hunks")
    return hunks


def locate_block(lines: List[str], old: List[str]) -> Tuple[List[int], str]:
    """Where a hunk's old-side block sits in the file: every line equal, else every line equal after rstrip(), else
    after strip(). The first tier with a match decides; its positions (0-based) and its name are returned."""
    n = len(old)
    for tier, norm in (("exact", None), ("rstrip", str.rstrip), ("strip", str.strip)):
        want = [norm(x) for x in old] if norm else old
        have = [norm(x) for x in lines] if norm else lines
        hits = [i for i in range(len(have) - n + 1) if have[i:i + n] == want]
        if hits:
            return hits, tier
    return [], "none"


def locate_hunks(lines: List[str], hunks: List[List[Tuple[str, str]]]) -> Union[List[Tuple[int, int, list]], str]:
    """(position, old-line count, hunk) for every hunk in file order, or the reason none is placed: a hunk without
    context or '-' lines has nothing to anchor on; a block must occur exactly once; hunks must stay in order and
    apart. The '+' lines never choose the place (they are what is not in the file yet)."""
    out: List[Tuple[int, int, list]] = []
    for k, h in enumerate(hunks, 1):
        old = [t for tag, t in h if tag != "+"]
        if not old:
            return f"hunk {k} has no context or '-' lines to anchor on"
        hits, tier = locate_block(lines, old)
        if not hits:
            return f"hunk {k}: its old lines are not in the file (first: {old[0].strip()[:60]!r})"
        if len(hits) > 1:
            return (f"hunk {k}: ambiguous, its old lines occur at {len(hits)} places (lines "
                    + ", ".join(str(i + 1) for i in hits[:6]) + "); add context lines that make it one")
        pos = hits[0]
        if out and pos < out[-1][0] + out[-1][1]:
            return f"hunk {k} (line {pos + 1}) overlaps or precedes hunk {k - 1} (line {out[-1][0] + 1})"
        out.append((pos, len(old), h))
    return out


def _indent_shift(lines: List[str], pos: int, hunk: List[Tuple[str, str]]) -> int:
    """How many spaces the file's lines are indented beyond the diff's (negative: fewer), when every non-blank old line
    of the hunk differs by the same amount; 0 otherwise. Live 2026-10-29 (quality self_patch_edit): the brain wrote
    "-    MAX_TEXT = 300" for a module-level line; placed by stripped content, its "+" line kept the four spaces, which
    is an IndentationError at the top of a module."""
    deltas = set()
    at = pos
    for tag, t in hunk:
        if tag == "+":
            continue
        have = lines[at] if at < len(lines) else ""
        at += 1
        if not t.strip() or not have.strip():
            continue
        deltas.add((len(have) - len(have.lstrip(" "))) - (len(t) - len(t.lstrip(" "))))
    return deltas.pop() if len(deltas) == 1 else 0


def apply_by_content(section_diff: str, path: Path) -> Union[Tuple[str, int], str]:
    """One file's diff applied by finding each hunk's old side in the file (locate_hunks). Returns (new text, hunks
    placed) or the reason it refused. The file's newline style (CRLF or LF) and its final newline stay as they are;
    where the diff's context differs from the file only in whitespace, the file's own line is kept."""
    try:
        hunks = parse_hunks(section_diff)
        text = path.read_bytes().decode("utf-8")
    except ValueError as e:
        return str(e)  # a UnicodeDecodeError is a ValueError
    except OSError as e:
        return f"cannot read {path.name}: {e}"
    crlf = "\r\n" in text
    body = text.replace("\r\n", "\n")
    lines = body.split("\n")
    trailing = body.endswith("\n")
    if trailing:
        lines.pop()
    placed = locate_hunks(lines, hunks)
    if isinstance(placed, str):
        return placed
    for pos, n_old, h in reversed(placed):  # from the bottom, so the earlier positions stay valid
        shift = _indent_shift(lines, pos, h)
        block, at = [], pos
        for tag, t in h:
            if tag == "+" and shift and t.strip():
                t = (" " * shift + t) if shift > 0 else (t[-shift:] if t[:-shift].strip() == "" else t.lstrip())
            if tag == " ":
                block.append(lines[at])
                at += 1
            elif tag == "-":
                at += 1
            else:
                block.append(t)
        lines[pos:pos + n_old] = block
    out = "\n".join(lines) + ("\n" if trailing else "")
    return (out.replace("\n", "\r\n") if crlf else out), len(placed)


def content_plan(diff: str, root: Path) -> Union[Dict[str, Any], str]:
    """Every file section of a diff placed by content, all computed before anything is written: {"texts": {path:
    bytes}, "hunks": n} or the reason the plan is refused. A new file or a deletion (a /dev/null side) is git's to
    apply, not the locator's, and refuses the whole plan; so does a file that is not there."""
    texts: Dict[str, bytes] = {}
    hunks = 0
    for section in file_sections(diff):
        old = new = None
        for line in section.split("\n"):
            if line.startswith("--- "):
                old = line[4:].split("\t")[0].strip()
            elif line.startswith("+++ "):
                new = line[4:].split("\t")[0].strip()
                break
        if not old or not new or "/dev/null" in (old, new):
            return f"{new or old or 'a section'}: a new file or a deletion is not placed by content"
        path = re.sub(r"^[ab]/", "", new)
        if not (root / path).is_file():
            return f"{path}: no such file"
        got = apply_by_content(section, root / path)
        if isinstance(got, str):
            return f"{path}: {got}"
        texts[path] = got[0].encode("utf-8")
        hunks += got[1]
    return {"texts": texts, "hunks": hunks}


def _restore(root: Path, before: Dict[str, Optional[bytes]]) -> None:
    for f, data in before.items():
        if data is None:
            (root / f).unlink(missing_ok=True)
        else:
            (root / f).write_bytes(data)


def apply_patch(diff: str, root: Optional[Path] = None, run: bool = True) -> Dict[str, Any]:
    """Apply a unified diff to the task's tree, compile the touched Python, run the covering tests."""
    root = root or work_root()
    diff = (diff or "").replace("\r\n", "\n")
    if not diff.strip():
        raise ValueError("empty patch")
    if len(diff) > PATCH_MAX_CHARS:
        raise ValueError(f"patch too large ({len(diff)} chars); split it")
    if not diff.endswith("\n"):
        diff += "\n"
    diff = normalize_headers(diff)
    files = diff_paths(diff)
    if not files:
        raise ValueError("not a unified diff: no '--- a/path' / '+++ b/path' headers")
    for f in files:
        if f.startswith("/") or re.match(r"^[A-Za-z]:", f) or ".." in Path(f).parts:
            meant = repo_relative(f, root)
            raise ValueError(f"{f}: paths must be repository-relative, inside the repository"
                             + (f"; write it as {meant} (paths start at the repository root, not in backend/)" if meant else ""))
    # As written first; then file by file with the hunk counts recounted (the brains' most common slip).
    # Live 2026-10-15 (objective 232): --recount on a whole multi-file diff read the next file's
    # "--- /dev/null" header as a line of the hunk before it, so every correct two-file patch failed.
    plans = [[(diff, [])], [(sec, ["--recount"]) for sec in file_sections(diff)]]
    # Live 2026-10-19 (objective 291): a hunk headed "@@ -303,4 +303,11 @@" held five old and twelve new lines; git
    # applied what the counts covered, ignored the rest without a word, and part of the change was released. When
    # the counts leave lines out, the file-by-file --recount plan is the only one.
    as_written = numstat(diff, [], root)
    recounted = [numstat(part, opts, root) for part, opts in plans[1]]
    if as_written is not None and None not in recounted and as_written != tuple(sum(c) for c in zip(*recounted)):
        plans = plans[1:]

    failure = located = None
    for plan in plans:
        checks = [(part, _git(["apply", "--check", *opts, "--whitespace=nowarn", "-"], root, stdin=part)) for part, opts in plan]
        failure = next(((part, c) for part, c in checks if c.returncode != 0), None)
        if failure is None:
            break
    else:
        # The file-by-file plan's verdict names the file and line that do not match; the whole diff's says only
        # "corrupt patch". Live 2026-10-15 (objective 266, attempt 2): three tries were told "corrupt patch at
        # <stdin>:56" with brains.py's context, while selfmodel.py's hunk at line 341 was the one that did not match.
        part, check = failure
        hint = context_hint(part, root)
        # Plan 3 (2026-10-25): the hunks placed by their lines, when every old-side block is in the file exactly once.
        located = content_plan(diff, root)
        if isinstance(located, str):
            raise ValueError("the patch does not apply cleanly: " + (check.stderr or check.stdout).strip()[:600]
                             + "\nMake the next diff from what the file holds now (context lines must match exactly):\n" + hint
                             + "\ncontent locator: " + located)
    # All or nothing: a section that fails after others applied puts the files back as they were (objective 266,
    # attempt 1: a half-applied patch was reported as failed, and the retry found its hunks "already applied").
    before = {f: ((root / f).read_bytes() if (root / f).is_file() else None) for f in files}
    if located is not None:
        try:
            for f, data in located["texts"].items():
                (root / f).write_bytes(data)
        except OSError as e:
            _restore(root, before)
            raise RuntimeError(f"writing the located hunks failed; nothing was changed: {e}")
    for part, opts in (plan if located is None else []):
        applied = _git(["apply", *opts, "--whitespace=nowarn", "-"], root, stdin=part)
        if applied.returncode != 0:
            _restore(root, before)
            raise RuntimeError("git apply failed after --check passed; nothing was changed: "
                               + (applied.stderr or applied.stdout).strip()[:600])
    report: Dict[str, Any] = {"root": str(root), "files": files, "compiled": [], "tests": None}
    if located is not None:
        report["relaxed"] = {"hunks": located["hunks"], "files": list(located["texts"])}
    broken = []
    for f in files:
        p = root / f
        if p.suffix == ".py" and p.is_file():
            try:
                compile(p.read_text(encoding="utf-8", errors="replace"), f, "exec")
                report["compiled"].append(f)
            except SyntaxError as e:
                broken.append(f"{f}: line {e.lineno}: {e.msg}")
    if broken:
        report["tests"] = {"ok": False, "ran": [], "summary": "not run: python does not compile: " + "; ".join(broken), "tail": ""}
        return report
    if run:
        tests = covering_tests(root, files)
        report["tests"] = run_tests(root, tests) if tests else {"ok": True, "ran": [], "summary": "no covering tests found: write one (backend/syrax/test_<module>.py) before you release", "tail": ""}
    return report


def render_report(rep: Dict[str, Any]) -> str:
    lines = [f"patched {len(rep['files'])} file(s) in {rep['root']}: " + ", ".join(rep["files"])]
    relaxed = rep.get("relaxed")
    if relaxed:
        lines.append(f"APPLIED BY CONTENT: {relaxed['hunks']} hunk(s) placed by matching their lines, not their line numbers"
                     " — the diff's context was stale; check the result")
    if rep["compiled"]:
        lines.append("compiled: " + ", ".join(rep["compiled"]))
    t = rep.get("tests")
    if t is not None:
        if not t["ok"]:
            prefix = "TESTS FAIL: "
        elif t["ran"]:
            prefix = "TESTS PASS: "
        else:
            prefix = "TESTS NOT RUN: "
        lines.append(prefix + t["summary"] + (f" ({', '.join(t['ran'])})" if t["ran"] else ""))
        if not t["ok"] and t.get("tail"):
            lines.append(t["tail"])
            lines.append("The patch is applied; fix forward with another patch or `undo`. A release with failing tests is rolled back.")
    return "\n".join(lines)


class RepoMapTool(BaseTool):
    name: str = "repo_map"
    description: str = (
        "Read-only map of your own repository: the system map's components (purpose, code files, the tests "
        "that cover them, known limitations) and the backend modules with their size and test file. Call it "
        "before changing your own code, with a query (a module name, a tool, a word from the task) to find "
        "where the change goes and which tests prove it."
    )
    parameters: dict = {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Filter: module, component, tool or keyword. Empty for everything."}},
    }

    async def execute(self, query: str = "", **_: Any) -> ToolResult:
        try:
            return ToolResult(output=render_map(work_root(), str(query or "").strip()))
        except Exception as e:
            return ToolResult(error=f"repo_map failed: {e}")


class ApplyPatchTool(BaseTool):
    name: str = "apply_patch"
    description: str = (
        "Change your own code with a unified diff (the `diff -u` / `git diff` format: '--- a/backend/syrax/x.py', "
        "'+++ b/backend/syrax/x.py', @@ hunks; new files diff from /dev/null). Paths are repository-relative. "
        "It applies the whole patch or nothing, compiles the touched Python and runs the tests that cover the "
        "touched files; the reply says what passed or failed. Then call `release` to commit it, unless you were told not to. Files that judge your work "
        "(quality cases, the gate, the guard, permissions, the journal) are refused: a human commits those."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "diff": {"type": "string", "description": "The unified diff."},
            "run_tests": {"type": "boolean", "description": "Run the covering tests after applying (default true)."},
        },
        "required": ["diff"],
    }
    async def execute(self, diff: str = "", run_tests: bool = True, **_: Any) -> ToolResult:
        import asyncio

        try:
            rep = await asyncio.to_thread(apply_patch, diff, None, bool(run_tests))
        except ValueError as e:
            return ToolResult(error=f"apply_patch refused: {e}")
        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            return ToolResult(error=f"apply_patch failed: {e}")
        return ToolResult(output=render_report(rep))  # a test failure is in the text; the patch itself succeeded
