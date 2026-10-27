"""SYRAX durable execution journal — the single source of truth for tasks,
events, checkpoints, recovery and verification records.

Design rules (see docs/EXECUTION_MODEL.md):
- SQLite, WAL, synchronous=FULL. Every write is one BEGIN IMMEDIATE ... COMMIT
  transaction: an event and the task-state change it implies are committed
  together or not at all.
- Task status changes only through the transition table below. Anything else
  raises JournalError and the transaction is rolled back.
- A task can only become SUCCESS/PARTIAL if a non-empty ``final`` event exists
  for it (no success without evidence).
- Recovery is idempotent: recovery events carry deterministic dedupe keys and
  run inside one transaction, so a crash during recovery loses nothing and a
  second run writes nothing.
- This module imports nothing from OpenManus so it can be used by crash-test
  child processes, CLI tools and future autonomous phases without booting the
  agent.

Wire translation: journal types are semantic (``tool.started``); ``Event.wire()``
maps them to the names the frontend already speaks (``tool_start``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional

from syrax import redact  # the one credential pattern; imports nothing but `re` itself
from syrax import intent  # the intent ledger's pure helpers (stdlib only)

log = logging.getLogger("syrax.journal")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILE = BACKEND_ROOT / "config" / "journal.db"
SCHEMA_VERSION = 1

STATUSES = (
    "PENDING",
    "IN_PROGRESS",
    "BLOCKED",
    "SUCCESS",
    "PARTIAL",
    "FAILED",
    "CANCELLED",
    "INTERRUPTED",
    "UNKNOWN",
)
TERMINAL = frozenset({"SUCCESS", "PARTIAL", "FAILED", "CANCELLED", "UNKNOWN"})
ACTIVE = frozenset({"IN_PROGRESS", "BLOCKED"})

TRANSITIONS: Dict[str, frozenset] = {
    "PENDING": frozenset({"IN_PROGRESS", "CANCELLED"}),
    "IN_PROGRESS": frozenset(
        {"BLOCKED", "SUCCESS", "PARTIAL", "FAILED", "CANCELLED", "INTERRUPTED"}
    ),
    "BLOCKED": frozenset({"IN_PROGRESS", "CANCELLED", "INTERRUPTED", "FAILED"}),
    "INTERRUPTED": frozenset({"IN_PROGRESS", "CANCELLED", "UNKNOWN", "FAILED"}),
    "SUCCESS": frozenset(),
    "PARTIAL": frozenset(),
    "FAILED": frozenset(),
    "CANCELLED": frozenset(),
    "UNKNOWN": frozenset(),
}

# Evidence states used by checkpoints and verifications.
EVIDENCE_STATES = ("SUCCESS", "PARTIAL", "FAILED", "BLOCKED", "UNKNOWN", "NOT_VERIFIED")

# Recovery classification of an interrupted task.
RECOVERY_STATES = ("RESUMABLE", "UNCERTAIN", "BLOCKED", "COMPLETED", "FAILED")

# Event types allowed on a task that is already terminal (read-only attachments).
TERMINAL_OK = frozenset({"verification.completed", "reflection.created", "knowledge.stored", "skill.verified", "skill.failed", "skill.not_tested", "skill.disabled", "presentation.created", "presentation.dismissed", "benchmark.completed", "experiment.completed", "rollback.created"})

# Tools whose side effects can be verified against the filesystem after a crash.
CHECKABLE_TOOLS = frozenset({"str_replace_editor"})
# F5: a call whose permission level only reads changed nothing, so repeating it after a crash
# is safe (live 2026-10-12: disk_usage on C:\ stayed UNCERTAIN and became a BLOCKED objective).
# Tools that run arbitrary code or page scripts are left out: their level is read from the code
# by patterns, which cannot rule out a side effect (python stays UNCERTAIN, test_journal).
NO_EFFECT_LEVELS = frozenset({"READ_ONLY", "EXTERNAL_READ"})
EXTERNAL_LEVEL = "EXTERNAL_WRITE"  # a send or payment in flight: EXTERNAL_UNCERTAIN, with its intent ledger entry
CODE_TOOLS = frozenset({"python_execute", "skill_create"})

MAX_CONTEXT_CHARS = 200_000
MAX_MESSAGE_CHARS = 8_000


# ——— one live owner per journal ———
# Crash recovery marks every unfinished task of an older boot INTERRUPTED. Run
# by a second process while the first is alive, it "recovers" live work (seen
# 2026-09-30: SYRAX ran `Core()` inside python_execute and its own running task
# was marked INTERRUPTED, then could not complete). The process that recovers
# holds an OS lock on <journal>.owner for as long as the journal is open; the
# OS drops it when the process dies, so real crash recovery still happens.
_OWNED: Dict[str, Any] = {}


def _lock_owner(db_path: Path) -> bool:
    """Take the owner lock for this journal. True when this process owns it
    (already or now), False when another live process holds it."""
    key = str(Path(db_path).resolve())
    if key in _OWNED:
        return True
    f = open(key + ".owner", "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return False
    _OWNED[key] = f
    return True


def _owned_elsewhere(db_path: Path) -> bool:
    """True when another live process owns this journal (probe and let go)."""
    key = str(Path(db_path).resolve())
    if key in _OWNED or not Path(key).exists():
        return False
    if not _lock_owner(db_path):
        return True
    _unlock_owner(db_path)
    return False


def _unlock_owner(db_path: Path) -> None:
    f = _OWNED.pop(str(Path(db_path).resolve()), None)
    if f is None:
        return
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    f.close()


class JournalError(RuntimeError):
    """A write was refused because it would make the journal lie."""


def _now() -> float:
    return time.time()


ALL_OBJECTIVES = 5000  # objectives() reads at most this many rows; full-set readers ask for this many


# A failed call where the tool did its job: it answered input it cannot act on (bad SQL, an old_str that is not
# in the file, a diff that does not apply, an exception in the caller's own code). Counted as a failure of the
# call, never as the tool failing: from 2026-09-30 to 2026-10-15 the cycle spent 40 tasks on "the tool failed on
# its last use, diagnose why" and 38 of them were DONE on the first harmless call, some with an invented cause
# ("a transient system error" for a query that named a column that does not exist).
_MISUSE = {
    "journal_query": re.compile(r"^Error: .*\. Schema: |^Error: only one read-only SELECT", re.S),
    "str_replace_editor": re.compile(r"^Error: (No replacement was performed|Parameter `\w+` is required|The path \S.* is not an "
                                     r"absolute path|The path \S.* does not exist|Invalid `view_range`|File already exists|Failed to read "
                                     r"|Unrecognized command|The path \S.* is a directory and only|The path \S.* is not absolute and was not found"
                                     r"|The editor cannot `)"),
    "desktop": re.compile(r"^Error: (\w+ needs |Nothing to open)"),
    "learn": re.compile(r"^Error: learn refused: cite"),
    "apply_patch": re.compile(r"^Error: apply_patch refused: (the patch does not apply cleanly|empty patch|not a unified diff|patch too large|"
                              r"[^\n]*paths must be repository-relative)"),
    # an exception in the caller's code; a timeout, a dead worker or an empty answer may be the tool's own fault
    "python_execute": re.compile(r"^\{'observation': (['\"])(?!Execution timeout|Error: the python_execute worker|\1)"),
}
# Any tool, skills included: input it cannot act on, in the words tools use for it. Live 2026-10-15: pdf_text
# called on a .txt file ("is not a PDF") and on a path that did not exist ("no file at") made a working skill
# FAILING, then a skill-repair objective.
_MISUSE_ANY = re.compile(r"\bno file at\b|\bis not an? (?:PDF|image|video|audio|text file|folder|directory)\b"
                         r"|\bpages? \d+(?:-\d+)? (?:is|are) outside\b", re.I)
_OBSERVED_PREFIX = re.compile(r"^Observed output of cmd `[^`]*` executed:\s*")


def misuse(name: Optional[str], output: Optional[str]) -> bool:
    """True when a failed call of `name` was the caller's mistake, judged from the tool's own error (_MISUSE),
    or, for any tool, from an error that names input it cannot act on (_MISUSE_ANY)."""
    body = _OBSERVED_PREFIX.sub("", str(output or ""), count=1)
    pat = _MISUSE.get(name or "")
    if pat and pat.search(body):
        return True
    return bool(name) and body.startswith("Error") and bool(_MISUSE_ANY.search(body[:400]))


_WORD = None


def re_words(text: str) -> List[str]:
    global _WORD
    if _WORD is None:
        import re

        _WORD = re.compile(r"[a-z0-9_]+")
    return _WORD.findall((text or "").lower())


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _loads(text: Optional[str], default: Any = None) -> Any:
    if text is None:
        return default
    try:
        return json.loads(text)
    except ValueError:
        return default


_SHA1_HEX = re.compile(r"[0-9a-f]{40}")
_FALLBACK = object()  # "not sure": ask git itself
# Any of these changes how git finds the repository or its refs: never guess, ask git.
_GIT_DISCOVERY_ENV = ("GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE", "GIT_CEILING_DIRECTORIES",
                      "GIT_DISCOVERY_ACROSS_FILESYSTEM", "GIT_NAMESPACE", "GIT_REF_STORAGE")


def _read_small(path: str) -> Optional[str]:
    """A small text file's content, or None when it is missing or unreadable."""
    try:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            return fh.read(64 * 1024)
    except (OSError, UnicodeDecodeError):
        return None


def _git_head_from_files(cwd: Path) -> Any:
    """HEAD's sha read from the repository files, None when cwd is in no repository,
    or _FALLBACK whenever anything is unusual (git then answers)."""
    if any(os.environ.get(k) for k in _GIT_DISCOVERY_ENV):
        return _FALLBACK
    start = os.path.realpath(str(cwd))
    if not os.path.isdir(start):
        return _FALLBACK
    # find the .git entry the way git's discovery does: walk up from cwd
    gitdir = None
    here = start
    while True:
        if os.path.basename(here).lower() == ".git":
            return _FALLBACK  # cwd inside a git dir: git's own rules apply
        dotgit = os.path.join(here, ".git")
        if os.path.isdir(dotgit):
            gitdir = dotgit
            break
        if os.path.isfile(dotgit):
            text = _read_small(dotgit)
            if text is None or not text.startswith("gitdir: ") or text.count("\n") > 1:
                return _FALLBACK
            target = text[len("gitdir: "):].strip()
            if not target:
                return _FALLBACK
            gitdir = os.path.normpath(os.path.join(here, target))
            break
        if os.path.exists(os.path.join(here, ".git")):
            return _FALLBACK  # .git of another kind
        if os.path.isfile(os.path.join(here, "HEAD")) and os.path.isdir(os.path.join(here, "objects")):
            return _FALLBACK  # looks like a bare repository
        parent = os.path.dirname(here)
        if parent == here:
            return None  # no repository above cwd: git says the same
        here = parent
    if not os.path.isdir(gitdir):
        return _FALLBACK
    common = gitdir
    if os.path.exists(os.path.join(gitdir, "commondir")):
        text = _read_small(os.path.join(gitdir, "commondir"))
        if text is None or not text.strip() or text.count("\n") > 1:
            return _FALLBACK
        common = os.path.normpath(os.path.join(gitdir, text.strip()))
    if not (os.path.isdir(os.path.join(common, "objects")) and os.path.isdir(os.path.join(common, "refs"))):
        return _FALLBACK
    if os.path.exists(os.path.join(common, "reftable")) or os.path.exists(os.path.join(gitdir, "reftable")):
        return _FALLBACK
    head = _read_small(os.path.join(gitdir, "HEAD"))
    if head is None or head.count("\n") > 1:
        return _FALLBACK
    head = head.rstrip("\n")
    if _SHA1_HEX.fullmatch(head):
        return head  # detached
    if not head.startswith("ref: "):
        return _FALLBACK
    ref = head[len("ref: "):]
    parts = ref.split("/")
    if (not ref.startswith("refs/heads/") or len(parts) < 3 or ref.endswith(".lock") or "\\" in ref
            or any(p in ("", ".", "..") or p.startswith(".") for p in parts)
            or any(c in ref for c in " ~^:?*[\r\t\x7f") or "@{" in ref
            or any(ord(c) < 32 for c in ref)):
        return _FALLBACK
    rel = os.path.join(*parts)
    if gitdir != common and os.path.exists(os.path.join(gitdir, rel)):
        return _FALLBACK  # a per-worktree copy git would not read: doubt
    loose = os.path.join(common, rel)
    if os.path.exists(loose):
        if not os.path.isfile(loose):
            return _FALLBACK
        text = _read_small(loose)
        if text is None or text.count("\n") > 1:
            return _FALLBACK
        text = text.rstrip("\n")
        return text if _SHA1_HEX.fullmatch(text) else _FALLBACK  # symbolic chains etc. go to git
    packed = _read_small(os.path.join(common, "packed-refs"))
    if packed is None:
        return _FALLBACK  # unborn branch or something odd
    for line in packed.split("\n"):
        if not line or line[0] in "#^":
            continue
        sha, sep, name = line.partition(" ")
        if sep and name.rstrip("\r") == ref:
            return sha if _SHA1_HEX.fullmatch(sha) else _FALLBACK
    return _FALLBACK


def _git_head(cwd: Path) -> Optional[str]:
    try:
        fast = _git_head_from_files(cwd)
    except Exception:
        fast = _FALLBACK
    if fast is not _FALLBACK:
        return fast
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


# ——— wire translation ———

_WIRE = {
    "tool.started": "tool_start",
    "tool.completed": "tool_result",
    "tool.failed": "tool_result",
    "answer": "user",
    "stage.started": "stage",
    "checkpoint.created": "checkpoint",
    "verification.completed": "verification",
}
_GROUPED = ("task", "recovery", "brain", "objective", "cycle", "reflection", "autonomy", "knowledge", "research", "skill", "code", "commit", "push", "rollback", "maintenance", "presentation", "benchmark", "experiment", "quality", "permission", "claim", "reminder", "alert", "topic", "checkin", "camera", "live", "presence", "intent", "change", "plan")


@dataclass(frozen=True)
class Event:
    id: int
    ts: float
    task_id: Optional[str]
    type: str
    seq: int
    payload: dict
    volatile: dict = field(default_factory=dict)  # fanned out, never stored

    def wire(self) -> dict:
        head, _, tail = self.type.partition(".")
        if head in _GROUPED and tail:
            out = {"type": head, "event": tail}
        else:
            out = {"type": _WIRE.get(self.type, self.type)}
        out.update(self.payload)
        out.update(self.volatile)
        out["event_id"] = self.id
        out["ts"] = self.ts
        if self.task_id:
            out["task_id"] = self.task_id
        return out


Subscriber = Callable[[Event], Awaitable[None]]
ResumeHook = Callable[[dict], Awaitable[None]]


_DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks (
  task_id            TEXT PRIMARY KEY,
  goal               TEXT NOT NULL,
  kind               TEXT NOT NULL DEFAULT 'conversation',
  status             TEXT NOT NULL CHECK (status IN
    ('PENDING','IN_PROGRESS','BLOCKED','SUCCESS','PARTIAL','FAILED','CANCELLED','INTERRUPTED','UNKNOWN')),
  stage              TEXT,
  current_step       INTEGER NOT NULL DEFAULT 0,
  created            REAL NOT NULL,
  updated            REAL NOT NULL,
  last_event_id      INTEGER,
  last_checkpoint_id INTEGER,
  operation          TEXT,
  result             TEXT,
  error              TEXT,
  recovery           TEXT,
  session_id         TEXT,
  boot_id            TEXT NOT NULL,
  git_head           TEXT
);
CREATE INDEX IF NOT EXISTS tasks_status_created ON tasks(status, created);
CREATE TABLE IF NOT EXISTS events (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  ts         REAL NOT NULL,
  task_id    TEXT REFERENCES tasks(task_id),
  type       TEXT NOT NULL,
  payload    TEXT NOT NULL,
  seq        INTEGER NOT NULL,
  dedupe_key TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS events_task_seq ON events(task_id, seq);
CREATE TABLE IF NOT EXISTS checkpoints (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id           TEXT NOT NULL REFERENCES tasks(task_id),
  seq               INTEGER NOT NULL,
  ts                REAL NOT NULL,
  stage             TEXT NOT NULL,
  completed_steps   TEXT NOT NULL,
  current_operation TEXT,
  verified          TEXT NOT NULL,
  remaining         TEXT,
  assumptions       TEXT NOT NULL,
  env               TEXT NOT NULL,
  next_action       TEXT,
  context           TEXT NOT NULL,
  evidence_state    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS checkpoints_task_seq ON checkpoints(task_id, seq);
CREATE TABLE IF NOT EXISTS verifications (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  ts       REAL NOT NULL,
  task_id  TEXT REFERENCES tasks(task_id),
  git_head TEXT,
  status   TEXT NOT NULL CHECK (status IN ('GREEN','BLOCKED')),
  gates    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS objectives (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  key          TEXT UNIQUE,
  goal         TEXT NOT NULL,
  reason       TEXT,
  priority     INTEGER NOT NULL DEFAULT 3,
  status       TEXT NOT NULL CHECK (status IN ('OPEN','ACTIVE','DONE','BLOCKED','DROPPED')),
  source       TEXT NOT NULL,
  check_spec   TEXT NOT NULL,
  evidence     TEXT NOT NULL,
  progress     TEXT NOT NULL,
  dependencies TEXT NOT NULL,
  next_action  TEXT,
  attempts     INTEGER NOT NULL DEFAULT 0,
  last_task_id TEXT,
  created      REAL NOT NULL,
  updated      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS objectives_status_priority ON objectives(status, priority, created);
CREATE TABLE IF NOT EXISTS knowledge (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  claim        TEXT NOT NULL,
  kind         TEXT NOT NULL CHECK (kind IN ('web','local','experiment','human','conclusion')),
  source_url   TEXT,
  source_title TEXT,
  excerpt      TEXT,
  confidence   REAL NOT NULL,
  basis        TEXT NOT NULL,
  sources      TEXT NOT NULL,
  tags         TEXT NOT NULL,
  question     TEXT,
  task_id      TEXT,
  created      REAL NOT NULL,
  last_used    REAL,
  uses         INTEGER NOT NULL DEFAULT 0,
  status       TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','DISPUTED','SUPERSEDED')),
  verified_at  REAL,
  superseded_by INTEGER
);
CREATE INDEX IF NOT EXISTS knowledge_created ON knowledge(created);
CREATE TABLE IF NOT EXISTS benchmarks (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  ts       REAL NOT NULL,
  git_head TEXT,
  metrics  TEXT NOT NULL,
  status   TEXT NOT NULL CHECK (status IN ('BASELINE','PASS','REGRESSION','NOT_VERIFIED')),
  compared_to INTEGER,
  deltas   TEXT NOT NULL,
  task_id  TEXT
);
CREATE TABLE IF NOT EXISTS quality_runs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  ts          REAL NOT NULL,
  git_head    TEXT,
  brain       TEXT,
  results     TEXT NOT NULL,
  pass_rate   REAL NOT NULL,
  status      TEXT NOT NULL CHECK (status IN ('BASELINE','PASS','REGRESSION')),
  compared_to INTEGER,
  delta       REAL
);
CREATE TABLE IF NOT EXISTS experiments (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  ts          REAL NOT NULL,
  hypothesis  TEXT NOT NULL,
  objective   TEXT,
  baseline    TEXT NOT NULL,
  candidate   TEXT NOT NULL,
  metric      TEXT NOT NULL,
  result      TEXT NOT NULL,
  conclusion  TEXT NOT NULL,
  verdict     TEXT NOT NULL CHECK (verdict IN ('CANDIDATE_BETTER','BASELINE_BETTER','NO_DIFFERENCE','INCONCLUSIVE')),
  next_action TEXT,
  task_id     TEXT
);
CREATE TABLE IF NOT EXISTS archive (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  ts            REAL NOT NULL,
  head          TEXT,
  parent        TEXT,
  decision      TEXT NOT NULL,
  summary       TEXT NOT NULL,
  objective_id  INTEGER,
  task_id       TEXT,
  experiment_id INTEGER,
  score         REAL,
  quality_run_id INTEGER
);
CREATE INDEX IF NOT EXISTS archive_head ON archive(head);
CREATE TABLE IF NOT EXISTS skills (
  name              TEXT PRIMARY KEY,
  version           INTEGER NOT NULL DEFAULT 1,
  purpose           TEXT NOT NULL,
  path              TEXT NOT NULL,
  status            TEXT NOT NULL CHECK (status IN ('NOT_TESTED','VERIFIED','FAILED','DISABLED')),
  tests_passed      INTEGER NOT NULL DEFAULT 0,
  tests_failed      INTEGER NOT NULL DEFAULT 0,
  evidence          TEXT NOT NULL,
  dependencies      TEXT NOT NULL,
  known_limitations TEXT NOT NULL,
  created_task_id   TEXT,
  created           REAL NOT NULL,
  updated           REAL NOT NULL,
  last_verified     REAL,
  content_hash      TEXT,
  code_version      INTEGER NOT NULL DEFAULT 1
);
"""

# Columns added after their table shipped (CREATE TABLE IF NOT EXISTS leaves an older journal without them), added in
# place at open. Additive only: no existing column changes meaning. 2026-10-25 (skill lifecycle): a skill's `version`
# keeps counting verifications; `code_version` follows its `content_hash` and moves only when the code does.
_ADDED_COLUMNS = (
    ("skills", "content_hash", "TEXT"),
    ("skills", "code_version", "INTEGER NOT NULL DEFAULT 1"),
    # knowledge state (audit 2026-10-27, item 4): DISPUTED was recomputed from recent events and aged out, and an
    # overwritten row left no row behind. Old rows become ACTIVE (the four rows the live journal's three contradiction
    # events name are all 78.4 vs 78.37 °C, which consolidate.agree has called the same figure since 2026-10-26, so
    # replaying those events would dispute correct rows); verified_at = created for every row that rests on a source
    # (every kind but human: add_knowledge_sync refuses the others without one), NULL for the human's own word.
    ("knowledge", "status", "TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','DISPUTED','SUPERSEDED'))"),
    ("knowledge", "verified_at", "REAL"),
    ("knowledge", "superseded_by", "INTEGER"),
)
# run once, in the transaction that adds the column
_BACKFILL = {
    ("knowledge", "verified_at"): "UPDATE knowledge SET verified_at=created WHERE kind!='human'",
}

# ACTIVE: believed. DISPUTED: another stored row contradicts it; shown marked, never stated as fact. SUPERSEDED: a
# newer row replaced it (superseded_by); kept for the record, skipped by retrieval. SUPERSEDED is final.
KNOWLEDGE_STATUSES = ("ACTIVE", "DISPUTED", "SUPERSEDED")
KNOWLEDGE_TRANSITIONS: Dict[str, frozenset] = {
    "ACTIVE": frozenset({"DISPUTED", "SUPERSEDED"}),
    "DISPUTED": frozenset({"ACTIVE", "SUPERSEDED"}),
    "SUPERSEDED": frozenset(),
}

SKILL_STATUSES = ("NOT_TESTED", "VERIFIED", "FAILED", "DISABLED")

KNOWLEDGE_KINDS = ("web", "local", "experiment", "human", "conclusion")
# Confidence policy: evidence decides, never the author.
CONFIDENCE_CEILING = {"web": 0.75, "local": 0.9, "experiment": 0.95, "human": 1.0, "conclusion": 0.9}


def confidence_for(kind: str, agreeing_sources: int = 1) -> float:
    if kind == "web":
        return {1: 0.4, 2: 0.6}.get(max(1, agreeing_sources), 0.75)
    return CONFIDENCE_CEILING.get(kind, 0.4)


def _memory_type(tags) -> str:
    """The memory type a `type:<t>` tag names (memory.TYPES: fact, preference, rule, observation); untagged rows are facts."""
    for t in tags or []:
        if str(t).startswith("type:"):
            return str(t)[5:]
    return "fact"


OBJECTIVE_STATUSES = ("OPEN", "ACTIVE", "DONE", "BLOCKED", "DROPPED")
OBJECTIVE_TRANSITIONS: Dict[str, frozenset] = {
    "OPEN": frozenset({"ACTIVE", "BLOCKED", "DROPPED", "DONE"}),
    "ACTIVE": frozenset({"OPEN", "DONE", "BLOCKED", "DROPPED"}),
    "BLOCKED": frozenset({"OPEN", "DROPPED", "DONE"}),
    "DONE": frozenset(),
    "DROPPED": frozenset({"OPEN"}),
}


class Journal:
    """Durable journal. Sync methods do the work; async ones wrap them in a
    worker thread and fan committed events out to subscribers."""

    _crash_hook: Optional[Callable[[str], None]] = None  # tests: simulate death inside a txn

    def __init__(
        self,
        path: Path | str = DEFAULT_FILE,
        boot_id: Optional[str] = None,
        recover: bool = True,
        repo_root: Optional[Path] = None,
    ) -> None:
        self.path = Path(path)
        self.boot_id = boot_id or uuid.uuid4().hex[:12]
        self.repo_root = Path(repo_root) if repo_root else BACKEND_ROOT.parent
        self.workspace_root = BACKEND_ROOT / "workspace"
        self._lock = threading.Lock()
        self._subs: List[Subscriber] = []
        # run(): the event ids its own worker thread inserts (see run), so it fans out only those
        self._mine = threading.local()
        self.recovered: List[dict] = []
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Another live process owns this journal: read it, never write it. Live
        # 2026-10-01: SYRAX built a second Core on Journal(recover=False) inside
        # python_execute, ran its own edited quality case there, and the stored
        # "pass" closed its objective. Only the owner records evidence.
        self.read_only = (not recover) and _owned_elsewhere(self.path)
        if self.read_only:
            self._owner = False
            self._db = sqlite3.connect(
                f"file:{self.path.resolve().as_posix()}?mode=ro", uri=True, check_same_thread=False, isolation_level=None, timeout=10
            )
            self._db.row_factory = sqlite3.Row
            # an owner still on the old schema: read it as it is (every row ACTIVE), never migrate it from here
            self._kstate = "status" in self._columns("knowledge")
            return
        self._db = sqlite3.connect(
            str(self.path), check_same_thread=False, isolation_level=None, timeout=10
        )
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(_DDL)
        self._add_columns()
        self._kstate = True
        self._db.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        self._owner = False
        if recover:
            if not _lock_owner(self.path):
                self._db.close()
                raise JournalError(
                    f"journal {self.path} is owned by another running SYRAX process; "
                    "a second core must not recover (it would mark live tasks INTERRUPTED). "
                    "Talk to the running SYRAX, or open the journal with recover=False to read it."
                )
            self._owner = True
            self.recovered = self.recover_interrupted()

    # ——— helpers ———

    def _columns(self, table: str) -> set:
        return {r["name"] for r in self._db.execute(f"PRAGMA table_info({table})").fetchall()}

    def _add_columns(self) -> None:
        """Add the _ADDED_COLUMNS an older file lacks, and their _BACKFILL, in one transaction: a crash between the
        ALTER and the backfill would leave the column added and never filled (the check below would skip it next time)."""
        if all(c in self._columns(t) for t, c, _ in _ADDED_COLUMNS):
            return
        self._db.execute("BEGIN IMMEDIATE")
        try:
            for table, column, decl in _ADDED_COLUMNS:  # re-read inside the lock: another process may have just added it
                if column not in self._columns(table):
                    self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
                    if (table, column) in _BACKFILL:
                        self._db.execute(_BACKFILL[(table, column)])
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise

    def _live(self) -> str:
        """The SQL condition for knowledge rows retrieval may return: not SUPERSEDED."""
        return "status!='SUPERSEDED'" if getattr(self, "_kstate", True) else "1"

    def _txn(self):
        return _Txn(self)

    def _row(self, cur: sqlite3.Cursor, task_id: str) -> sqlite3.Row:
        row = cur.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise JournalError(f"unknown task {task_id}")
        return row

    @staticmethod
    def _transition(current: str, new: str) -> None:
        if current == new:
            return
        if new not in TRANSITIONS.get(current, frozenset()):
            raise JournalError(f"invalid transition {current} -> {new}")

    def _insert_event(
        self,
        cur: sqlite3.Cursor,
        ts: float,
        task_id: Optional[str],
        type_: str,
        payload: dict,
        dedupe_key: Optional[str] = None,
    ) -> Optional[int]:
        seq = 0
        if task_id:
            seq = (
                cur.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE task_id=?", (task_id,)
                ).fetchone()[0]
            )
        if dedupe_key:
            cur.execute(
                "INSERT OR IGNORE INTO events(ts, task_id, type, payload, seq, dedupe_key) "
                "VALUES (?,?,?,?,?,?)",
                (ts, task_id, type_, _dumps(payload), seq, dedupe_key),
            )
            if cur.rowcount == 0:
                return None
        else:
            cur.execute(
                "INSERT INTO events(ts, task_id, type, payload, seq) VALUES (?,?,?,?,?)",
                (ts, task_id, type_, _dumps(payload), seq),
            )
        ev_id = int(cur.lastrowid)
        mine = getattr(self._mine, "ids", None)
        if mine is not None:
            mine.append(ev_id)
        return ev_id

    def _apply(self, cur: sqlite3.Cursor, row: sqlite3.Row, type_: str, payload: dict, ev_id: int, ts: float) -> None:
        """Derive the task-row change implied by an event. Same transaction."""
        status = row["status"]
        if status in TERMINAL and type_ not in TERMINAL_OK:
            raise JournalError(f"task {row['task_id']} is {status}; refusing {type_}")
        upd: Dict[str, Any] = {"updated": ts, "last_event_id": ev_id}
        new_status = status
        if type_ == "task.started":
            new_status = "IN_PROGRESS"
            upd["stage"] = "started"
        elif type_ == "stage.started":
            upd["stage"] = str(payload.get("stage") or "")
        elif type_ == "think":
            upd["stage"] = "thinking"
            if isinstance(payload.get("step"), int):
                upd["current_step"] = payload["step"]
        elif type_ == "tool.started":
            name = str(payload.get("name") or "?")
            upd["stage"] = f"tool:{name}"
            upd["operation"] = _dumps(
                {
                    "id": payload.get("id"),
                    "name": name,
                    "args": payload.get("args"),
                    "step": payload.get("step"),
                    "started": ts,
                }
            )
        elif type_ in ("tool.completed", "tool.failed"):
            upd["stage"] = f"observed:{payload.get('name') or '?'}"
            upd["operation"] = None
            if status == "BLOCKED":
                new_status = "IN_PROGRESS"
        elif type_ == "ask":
            new_status = "BLOCKED"
            upd["stage"] = "asking"
        elif type_ == "answer":
            new_status = "IN_PROGRESS"
            upd["stage"] = "answered"
        elif type_ == "final":
            upd["stage"] = "final"
            upd["result"] = str(payload.get("text") or "")
        elif type_ == "checkpoint.created":
            upd["last_checkpoint_id"] = payload.get("checkpoint_id")
        elif type_ == "task.completed":
            wanted = str(payload.get("status") or "")
            if wanted not in ("SUCCESS", "PARTIAL"):
                raise JournalError(f"task.completed needs status SUCCESS|PARTIAL, got {wanted!r}")
            has_final = cur.execute(
                "SELECT 1 FROM events WHERE task_id=? AND type='final' "
                "AND json_extract(payload, '$.text') <> '' LIMIT 1",
                (row["task_id"],),
            ).fetchone()
            if not has_final:
                raise JournalError("task.completed without a final event: no evidence of a result")
            new_status = wanted
            upd["stage"] = "done"
        elif type_ == "task.failed":
            new_status = "FAILED"
            upd["stage"] = "done"
            upd["error"] = str(payload.get("error") or "failed")
        elif type_ == "task.cancelled":
            new_status = "CANCELLED"
            upd["stage"] = "done"
            upd["error"] = str(payload.get("error") or "cancelled")
        elif type_ == "task.blocked":
            new_status = "BLOCKED"
            upd["error"] = str(payload.get("reason") or "blocked")
        elif type_ == "task.interrupted":
            new_status = "INTERRUPTED"
            upd["error"] = str(payload.get("error") or "interrupted")
            upd["recovery"] = _dumps(payload.get("recovery") or {})
        elif type_ == "task.unknown":
            new_status = "UNKNOWN"
            upd["error"] = str(payload.get("error") or "outcome unknown")
        elif type_ == "recovery.resumed":
            new_status = "IN_PROGRESS"
            upd["stage"] = "resumed"
            upd["boot_id"] = str(payload.get("boot_id") or self.boot_id)
            if payload.get("session_id"):
                upd["session_id"] = str(payload["session_id"])
        # recovery.verified, verification.completed, brain.*, unknown future
        # types: recorded, no state change.
        self._transition(status, new_status)
        upd["status"] = new_status
        cols = ", ".join(f"{k}=?" for k in upd)
        cur.execute(f"UPDATE tasks SET {cols} WHERE task_id=?", (*upd.values(), row["task_id"]))

    # ——— sync API ———

    def start_task_sync(
        self,
        goal: str,
        session_id: Optional[str] = None,
        kind: str = "conversation",
        pending: bool = False,
    ) -> str:
        """A new task row and its task.started (or task.queued) event. The stored goal is the journal's copy of the
        human's words, masked (audit 2026-10-25: a key pasted into a request landed in the journal); the caller keeps
        the raw text for the agent."""
        goal = redact.mask(goal)
        task_id = uuid.uuid4().hex[:12]
        ts = _now()
        status = "PENDING" if pending else "IN_PROGRESS"
        with self._txn() as cur:
            cur.execute(
                "INSERT INTO tasks(task_id, goal, kind, status, stage, created, updated, "
                "session_id, boot_id, git_head) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    task_id,
                    goal,
                    kind,
                    status,
                    "queued" if pending else "started",
                    ts,
                    ts,
                    session_id,
                    self.boot_id,
                    _git_head(self.repo_root),
                ),
            )
            type_ = "task.queued" if pending else "task.started"
            ev_id = self._insert_event(cur, ts, task_id, type_, {"goal": goal, "kind": kind})
            cur.execute(
                "UPDATE tasks SET last_event_id=? WHERE task_id=?", (ev_id, task_id)
            )
        return task_id

    def record_sync(
        self,
        type_: str,
        payload: Optional[dict] = None,
        task_id: Optional[str] = None,
        volatile: Optional[dict] = None,
        dedupe_key: Optional[str] = None,
    ) -> Optional[Event]:
        payload = dict(payload or {})
        ts = _now()
        with self._txn() as cur:
            row = self._row(cur, task_id) if task_id else None
            ev_id = self._insert_event(cur, ts, task_id, type_, payload, dedupe_key)
            if ev_id is None:
                return None  # deduplicated
            seq = cur.execute("SELECT seq FROM events WHERE id=?", (ev_id,)).fetchone()[0]
            if row is not None:
                self._apply(cur, row, type_, payload, ev_id, ts)
        return Event(ev_id, ts, task_id, type_, seq, payload, dict(volatile or {}))

    def checkpoint_sync(
        self,
        task_id: str,
        stage: str,
        completed_steps: Optional[list] = None,
        current_operation: Optional[dict] = None,
        verified: Optional[dict] = None,
        remaining: Optional[str] = None,
        assumptions: Optional[list] = None,
        next_action: Optional[str] = None,
        context: Optional[list] = None,
        evidence_state: str = "NOT_VERIFIED",
    ) -> Event:
        """A checkpoint row (plus its checkpoint.created event) a resume can start from. The stored ``context`` is a
        bounded, masked copy of the agent's messages (audit 2026-10-25: it held every tool output as it came, keys
        included); the agent's live memory is untouched. So a task resumed from a checkpoint reads
        "[credential masked]" where a key was: a key in a resumed context is the exception, the journal is evidence."""
        if evidence_state not in EVIDENCE_STATES:
            raise JournalError(f"bad evidence_state {evidence_state!r}")
        ts = _now()
        ctx = redact.mask_deep(_bound_context(context or []))
        with self._txn() as cur:
            row = self._row(cur, task_id)
            if row["status"] in TERMINAL:
                raise JournalError(f"task {task_id} is {row['status']}; no checkpoint")
            seq = cur.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM checkpoints WHERE task_id=?", (task_id,)
            ).fetchone()[0]
            env = {
                "git_head": _git_head(self.repo_root),
                "workspace_root": str(self.workspace_root),
                "cwd": os.getcwd(),
                "boot_id": self.boot_id,
            }
            cur.execute(
                "INSERT INTO checkpoints(task_id, seq, ts, stage, completed_steps, current_operation, "
                "verified, remaining, assumptions, env, next_action, context, evidence_state) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    task_id,
                    seq,
                    ts,
                    stage,
                    _dumps(completed_steps or []),
                    _dumps(current_operation) if current_operation else None,
                    _dumps(verified or {}),
                    remaining,
                    _dumps(assumptions or []),
                    _dumps(env),
                    next_action,
                    _dumps(ctx),
                    evidence_state,
                ),
            )
            cp_id = int(cur.lastrowid)
            payload = {
                "checkpoint_id": cp_id,
                "seq": seq,
                "stage": stage,
                "completed_steps": len(completed_steps or []),
                "evidence_state": evidence_state,
                "next_action": next_action,
            }
            ev_id = self._insert_event(cur, ts, task_id, "checkpoint.created", payload)
            ev_seq = cur.execute("SELECT seq FROM events WHERE id=?", (ev_id,)).fetchone()[0]
            self._apply(cur, row, "checkpoint.created", payload, ev_id, ts)
        return Event(ev_id, ts, task_id, "checkpoint.created", ev_seq, payload)

    def record_verification_sync(self, result: dict, task_id: Optional[str] = None) -> Event:
        ts = _now()
        status = "GREEN" if result.get("status") == "GREEN" else "BLOCKED"
        gates = result.get("gates") or []
        head = result.get("git_head") or _git_head(self.repo_root)
        with self._txn() as cur:
            row = self._row(cur, task_id) if task_id else None
            cur.execute(
                "INSERT INTO verifications(ts, task_id, git_head, status, gates) VALUES (?,?,?,?,?)",
                (ts, task_id, head, status, _dumps(gates)),
            )
            vid = int(cur.lastrowid)
            payload = {
                "verification_id": vid,
                "status": status,
                "git_head": head,
                "gates": [
                    {"name": g.get("name"), "status": g.get("status"), "required": g.get("required")}
                    for g in gates
                ],
            }
            ev_id = self._insert_event(cur, ts, task_id, "verification.completed", payload)
            seq = cur.execute("SELECT seq FROM events WHERE id=?", (ev_id,)).fetchone()[0]
            if row is not None:
                self._apply(cur, row, "verification.completed", payload, ev_id, ts)
        return Event(ev_id, ts, task_id, "verification.completed", seq, payload)

    # ——— recovery ———

    def verify_operation(self, op: Optional[dict], cur: Optional[sqlite3.Cursor] = None, task_id: Optional[str] = None,
                         head_unchanged: Optional[bool] = None) -> dict:
        """Compare a persisted in-flight operation with reality.

        Returns {"state": COMPLETED|NOT_STARTED|PARTIAL|HARMLESS|UNCERTAIN|NONE, "checks": {...}}.
        Filesystem edits are checked against the files. A call that only reads is HARMLESS.
        Anything else is UNCERTAIN, with its permission level and the targets it names, so
        a human sees exactly what it may have touched.
        """
        if not op:
            return {"state": "NONE", "checks": {}}
        name = str(op.get("name") or "")
        args = op.get("args") if isinstance(op.get("args"), dict) else {}
        if name == "ask_human":
            return {"state": "BLOCKED", "checks": {"question": args.get("inquire")}}
        if name == "release" and task_id:
            # live 2026-10-15: SYRAX stopped while its own release gated (objective 224, attempt 5) and recovery left
            # it UNCERTAIN for a human. A release commits only after its gate: the journal and git say whether it did.
            q = "SELECT payload FROM events WHERE task_id=? AND type='commit.created' ORDER BY id DESC LIMIT 1"
            found = (cur.execute(q, (task_id,)) if cur is not None else self._db.execute(q, (task_id,))).fetchone()
            if found:
                return {"state": "COMPLETED", "checks": {"commit": (_loads(found[0]) or {}).get("commit"), "reason": "the release committed"}}
            if head_unchanged:
                return {"state": "NOT_STARTED", "checks": {"reason": "no commit was created and the repository HEAD has not moved: "
                                                                     "the gate did not finish and nothing landed"}}
            return {"state": "UNCERTAIN", "checks": {"reason": "no commit is journaled but HEAD moved since the task began: "
                                                               "a human checks whether the release landed"}}
        if name not in CHECKABLE_TOOLS:
            seen = self._effects_of(name, args, cur)
            # the intent ledger (intent.py): a send or payment in flight, by its level or by an intent.recorded this task
            # never saw done, may already have gone out; a human verifies before anything repeats it
            held = [i for i in (self.open_intents(task_id, cur) if task_id else []) if i.get("tool") == name]
            if seen["level"] == EXTERNAL_LEVEL or held:
                rec = held[-1] if held else intent.entry(name, args, op.get("step"))
                return {"state": "EXTERNAL_UNCERTAIN", "intent": rec,
                        "checks": {**seen, "reason": f"{name} may have sent a message or money ({rec['summary']}); verify before repeating"}}
            if seen["level"] in NO_EFFECT_LEVELS and not seen["harm"] and name not in CODE_TOOLS and not name.startswith("browser_"):
                return {"state": "HARMLESS", "checks": {**seen, "reason": f"{name} only reads ({seen['level']}); repeating it changes nothing"}}
            return {"state": "UNCERTAIN", "checks": {**seen, "reason": f"{name} side effects cannot be inspected"}}
        cmd = str(args.get("command") or "")
        path = Path(str(args.get("path") or ""))
        checks: Dict[str, Any] = {"command": cmd, "path": str(path), "exists": path.is_file()}
        if cmd == "view":
            return {"state": "COMPLETED", "checks": checks}
        if not path.is_file():
            if cmd == "create":
                return {"state": "NOT_STARTED", "checks": checks}
            return {"state": "UNCERTAIN", "checks": {**checks, "reason": "target file missing"}}
        try:
            # the editor (file_operators.py) writes UTF-8; the locale here is cp1252 (utf8_mode 0), so a default
            # read turned an em dash or Bengali in new_str into mojibake: COMPLETED edits looked UNCERTAIN/PARTIAL
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return {"state": "UNCERTAIN", "checks": {**checks, "reason": str(e)}}
        if cmd == "create":
            wanted = str(args.get("file_text") or "")
            checks["content_matches"] = text == wanted
            return {"state": "COMPLETED" if text == wanted else "PARTIAL", "checks": checks}
        if cmd in ("str_replace", "insert"):
            new = str(args.get("new_str") or "")
            old = str(args.get("old_str") or "")
            checks["new_present"] = bool(new) and new in text
            checks["old_present"] = bool(old) and old in text
            if new and new in text and not (old and old in text):
                return {"state": "COMPLETED", "checks": checks}
            if old and old in text and not (new and new in text):
                return {"state": "NOT_STARTED", "checks": checks}
            return {"state": "UNCERTAIN", "checks": checks}
        return {"state": "UNCERTAIN", "checks": checks}

    def open_intents(self, task_id: str, cur: Optional[sqlite3.Cursor] = None) -> List[dict]:
        """The task's intent.recorded entries without an intent.done (intent.py open_of): sends that may have gone
        out. Recovery passes its own cursor (it holds the journal lock)."""
        q = "SELECT type, payload FROM events WHERE task_id=? AND type IN ('intent.recorded', 'intent.done') ORDER BY seq, id"
        rows = (cur.execute(q, (task_id,)) if cur is not None else self._db.execute(q, (task_id,))).fetchall()
        return intent.open_of((str(r[0]), _loads(r[1]) or {}) for r in rows)

    def _effects_of(self, name: str, args: dict, cur: Optional[sqlite3.Cursor] = None) -> dict:
        """The permission level, targets and harm of a call (permissions.py). A skill's level
        comes from its registry row, because at recovery the skills are not declared yet.
        Recovery passes its own cursor: it holds the journal lock, and self.skill() would wait on it."""
        from syrax import permissions  # permissions imports this module

        try:
            d = permissions.classify(name, args)
            level, targets, harm = d.level, [str(t) for t in d.targets][:20], list(d.harm)
        except Exception:
            level, targets, harm = permissions.SYSTEM, [], []
        if cur is not None:
            found = cur.execute("SELECT * FROM skills WHERE name=?", (name,)).fetchone()
            row = self._skill_dict(found) if found else None
        else:
            row = self.skill(name)
        if row is not None:
            risk = str((row.get("evidence") or {}).get("risk") or "")
            level = risk if row.get("status") == "VERIFIED" and risk in permissions.ORDER else permissions.SYSTEM
        return {"level": level, "targets": targets, "harm": harm}

    def recover_interrupted(self) -> List[dict]:
        """Mark tasks left active by a previous process as INTERRUPTED, after
        checking what really happened. Idempotent; one transaction."""
        reports: List[dict] = []
        with self._txn() as cur:
            rows = cur.execute(
                "SELECT * FROM tasks WHERE status IN ('IN_PROGRESS','BLOCKED') AND boot_id != ? "
                "ORDER BY created",
                (self.boot_id,),
            ).fetchall()
            if not rows:
                return []
            ts = _now()
            ids = [r["task_id"] for r in rows]
            last_ids = [str(r["last_event_id"] or 0) for r in rows]
            key = f"{','.join(ids)}:{','.join(last_ids)}"
            self._insert_event(
                cur, ts, None, "recovery.started",
                {"boot_id": self.boot_id, "task_ids": ids},
                dedupe_key=f"recovery.started:{key}",
            )
            head_now = _git_head(self.repo_root)
            for row in rows:
                report = self._recovery_report(cur, row, head_now)
                self._insert_event(
                    cur, ts, row["task_id"], "recovery.verified",
                    {"recovery": report["recovery"]},
                    dedupe_key=f"recovery.verified:{row['task_id']}:{row['last_event_id']}",
                )
                payload = {
                    "error": report["error"],
                    "goal": row["goal"],
                    "step": row["current_step"],
                    "stage": row["stage"],
                    "tool": report["tool"],
                    "question": report["question"],
                    "recovery_state": report["recovery"]["state"],
                    "recovery": report["recovery"],
                }
                ev_id = self._insert_event(
                    cur, ts, row["task_id"], "task.interrupted", payload,
                    dedupe_key=f"task.interrupted:{row['task_id']}:{row['last_event_id']}",
                )
                if ev_id is not None:
                    self._apply(cur, row, "task.interrupted", payload, ev_id, ts)
                reports.append(report)
            self._insert_event(
                cur, ts, None, "recovery.completed",
                {"boot_id": self.boot_id, "count": len(reports), "task_ids": ids},
                dedupe_key=f"recovery.completed:{key}",
            )
            if Journal._crash_hook is not None:
                Journal._crash_hook("recovery")
        return reports

    def _recovery_report(self, cur: sqlite3.Cursor, row: sqlite3.Row, head_now: Optional[str]) -> dict:
        last = cur.execute(
            "SELECT id, type, ts, seq FROM events WHERE task_id=? ORDER BY seq DESC LIMIT 1",
            (row["task_id"],),
        ).fetchone()
        cp = cur.execute(
            "SELECT id, seq, stage, ts, evidence_state FROM checkpoints WHERE task_id=? "
            "ORDER BY seq DESC LIMIT 1",
            (row["task_id"],),
        ).fetchone()
        op = _loads(row["operation"])
        verdict = self.verify_operation(op, cur, task_id=row["task_id"],
                                        head_unchanged=(row["git_head"] == head_now) if row["git_head"] and head_now else None)
        op_state = verdict["state"]
        if row["status"] == "BLOCKED" or op_state == "BLOCKED":
            state = "BLOCKED"
        elif op_state in ("NONE", "COMPLETED", "NOT_STARTED", "HARMLESS"):
            state = "RESUMABLE"
        else:
            state = "UNCERTAIN"
        checks = {
            "journal_consistent": bool(last) and last["id"] == row["last_event_id"],
            "git_head_unchanged": (row["git_head"] == head_now) if row["git_head"] else None,
            "workspace_present": self.workspace_root.is_dir(),
            "operation": verdict["checks"],
        }
        recovery = {
            "state": state,
            "operation_state": op_state,
            "operation": op,
            "intent": verdict.get("intent"),  # the send that may have gone out (EXTERNAL_UNCERTAIN), else None
            "checks": checks,
            "last_event_id": row["last_event_id"],
            "last_checkpoint_id": cp["id"] if cp else None,
            "resume_from": (f"checkpoint:{cp['id']}" if cp else "goal"),
            "previous_boot_id": row["boot_id"],
            "boot_id": self.boot_id,
        }
        tool = op.get("name") if op else None
        question = (op.get("args") or {}).get("inquire") if op and tool == "ask_human" else None
        return {
            "task_id": row["task_id"],
            "goal": row["goal"],
            "last_event": dict(last) if last else None,
            "last_stage": row["stage"],
            "last_step": row["current_step"],
            "tool": tool,
            "question": question,
            "recovery": recovery,
            "error": f"interrupted at step {row['current_step']} during {row['stage'] or 'start'}"
            + (f" (operation {tool}: {op_state})" if tool else ""),
        }

    def resume_context(self, task_id: str) -> dict:
        task = self.task(task_id)
        if task is None:
            raise JournalError(f"unknown task {task_id}")
        if task["status"] != "INTERRUPTED":
            raise JournalError(f"task {task_id} is {task['status']}, not INTERRUPTED")
        cp = self.latest_checkpoint(task_id)
        return {"task": task, "checkpoint": cp, "recovery": task.get("recovery") or {}}

    def mark_resumed_sync(self, task_id: str, session_id: Optional[str] = None) -> Event:
        ev = self.record_sync(
            "recovery.resumed",
            {"session_id": session_id, "boot_id": self.boot_id},
            task_id=task_id,
        )
        assert ev is not None
        return ev

    # ——— objectives ———

    @staticmethod
    def _objective_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        for k in ("check_spec", "evidence", "progress", "dependencies"):
            d[k] = _loads(d.get(k), {} if k != "dependencies" else [])
        return d

    def add_objective_sync(
        self,
        goal: str,
        reason: Optional[str] = None,
        priority: int = 3,
        source: str = "human",
        check: Optional[dict] = None,
        key: Optional[str] = None,
        dependencies: Optional[List[int]] = None,
        status: str = "OPEN",
        evidence: Optional[dict] = None,
        next_action: Optional[str] = None,
    ) -> Optional[dict]:
        """Create an objective. With ``key`` it is idempotent: an existing key
        returns None (nothing written)."""
        if status not in OBJECTIVE_STATUSES:
            raise JournalError(f"bad objective status {status!r}")
        ts = _now()
        with self._txn() as cur:
            if key and cur.execute("SELECT 1 FROM objectives WHERE key=?", (key,)).fetchone():
                return None
            cur.execute(
                "INSERT INTO objectives(key, goal, reason, priority, status, source, check_spec, evidence, "
                "progress, dependencies, next_action, created, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    key, goal, reason, int(priority), status, source,
                    _dumps(check or {"kind": "task_success"}), _dumps(evidence or {}), _dumps({}),
                    _dumps(dependencies or []), next_action, ts, ts,
                ),
            )
            oid = int(cur.lastrowid)
            self._insert_event(
                cur, ts, None, "objective.created",
                {"objective_id": oid, "goal": goal, "priority": int(priority), "source": source, "status": status, "key": key},
            )
        return self.objective(oid)

    def update_objective_sync(
        self,
        objective_id: int,
        status: Optional[str] = None,
        progress: Optional[dict] = None,
        evidence: Optional[dict] = None,
        next_action: Optional[str] = None,
        last_task_id: Optional[str] = None,
        bump_attempts: bool = False,
        note: Optional[str] = None,
    ) -> dict:
        ts = _now()
        with self._txn() as cur:
            row = cur.execute("SELECT * FROM objectives WHERE id=?", (objective_id,)).fetchone()
            if row is None:
                raise JournalError(f"unknown objective {objective_id}")
            current = row["status"]
            new_status = status or current
            if new_status != current and new_status not in OBJECTIVE_TRANSITIONS[current]:
                raise JournalError(f"invalid objective transition {current} -> {new_status}")
            upd: Dict[str, Any] = {"updated": ts, "status": new_status}
            if progress is not None:
                upd["progress"] = _dumps({**_loads(row["progress"], {}), **progress})
            if evidence is not None:
                upd["evidence"] = _dumps({**_loads(row["evidence"], {}), **evidence})
            if next_action is not None:
                upd["next_action"] = next_action
            if last_task_id is not None:
                upd["last_task_id"] = last_task_id
            if bump_attempts:
                upd["attempts"] = int(row["attempts"]) + 1
            cols = ", ".join(f"{k}=?" for k in upd)
            cur.execute(f"UPDATE objectives SET {cols} WHERE id=?", (*upd.values(), objective_id))
            kind = {
                "DONE": "objective.completed", "BLOCKED": "objective.blocked", "DROPPED": "objective.dropped",
            }.get(new_status if new_status != current else "", "objective.updated")
            self._insert_event(
                cur, ts, last_task_id, kind,
                {"objective_id": objective_id, "status": new_status, "attempts": upd.get("attempts", row["attempts"]),
                 "note": note, "evidence": evidence or {}},
            )
        return self.objective(objective_id)

    def reopen_objective_sync(self, objective_id: int, note: str) -> dict:
        """A human's override: put a DONE objective back to OPEN because the
        evidence that closed it was wrong (2026-10-01: SYRAX closed one with a
        quality run it ran on its own edited case). DONE stays terminal for
        every other path; this one requires a note and is journaled as such."""
        if not (note or "").strip():
            raise JournalError("reopening needs a note saying why the evidence was wrong")
        ts = _now()
        with self._txn() as cur:
            row = cur.execute("SELECT * FROM objectives WHERE id=?", (objective_id,)).fetchone()
            if row is None:
                raise JournalError(f"unknown objective {objective_id}")
            if row["status"] != "DONE":
                raise JournalError(f"objective {objective_id} is {row['status']}, not DONE")
            cur.execute("UPDATE objectives SET status='OPEN', attempts=0, updated=? WHERE id=?", (ts, objective_id))
            self._insert_event(cur, ts, None, "objective.reopened",
                               {"objective_id": objective_id, "status": "OPEN", "note": note, "previous_evidence": _loads(row["evidence"], {})})
        return self.objective(objective_id)

    def objective(self, objective_id: int) -> Optional[dict]:
        with self._lock:
            row = self._db.execute("SELECT * FROM objectives WHERE id=?", (objective_id,)).fetchone()
        return self._objective_dict(row) if row else None

    def objectives(self, limit: int = 50, status: Optional[str | Iterable[str]] = None) -> List[dict]:
        """By priority, then age. Callers that need every row pass a limit above the table's size (ALL_OBJECTIVES)."""
        limit = max(1, min(int(limit), ALL_OBJECTIVES))
        sql = "SELECT * FROM objectives"
        params: list = []
        if status:
            statuses = [status] if isinstance(status, str) else list(status)
            sql += f" WHERE status IN ({','.join('?' * len(statuses))})"
            params += statuses
        sql += " ORDER BY priority, created LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._db.execute(sql, params).fetchall()
        return [self._objective_dict(r) for r in rows]

    def objectives_since(self, ts: float, limit: int = 500) -> List[dict]:
        """Objectives created at or after `ts`, newest first. Live 2026-10-15: the known-limitation cap counted
        "today's" objectives in objectives(limit=200), ordered by priority then age; with 262 rows the newest
        priority-3 ones fell outside the 200 and the cap of 3 a day let 7 through."""
        limit = max(1, min(int(limit), ALL_OBJECTIVES))
        with self._lock:
            rows = self._db.execute("SELECT * FROM objectives WHERE created>=? ORDER BY created DESC, id DESC LIMIT ?", (ts, limit)).fetchall()
        return [self._objective_dict(r) for r in rows]

    # ——— knowledge (provenance-aware) ———

    @staticmethod
    def _knowledge_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["sources"] = _loads(d.get("sources"), [])
        d["tags"] = _loads(d.get("tags"), [])
        d.setdefault("status", "ACTIVE")  # a read-only handle on an owner still on the old schema
        d.setdefault("verified_at", None)
        d.setdefault("superseded_by", None)
        return d

    def add_knowledge_sync(
        self,
        claim: str,
        kind: str,
        source_url: Optional[str] = None,
        source_title: Optional[str] = None,
        excerpt: Optional[str] = None,
        sources: Optional[list] = None,
        tags: Optional[List[str]] = None,
        question: Optional[str] = None,
        task_id: Optional[str] = None,
        confidence: Optional[float] = None,
        agreeing_sources: int = 1,
        basis: Optional[str] = None,
    ) -> dict:
        """Store a fact with provenance. Confidence is capped by the evidence
        kind; a caller may lower it, never raise it above the policy. A row stored with a source is verified now
        (verified_at); the human's own word (kind human) has no source to check and stays unverified."""
        if kind not in KNOWLEDGE_KINDS:
            raise JournalError(f"bad knowledge kind {kind!r}")
        claim = (claim or "").strip()
        if not claim:
            raise JournalError("empty claim")
        if kind != "human" and not (source_url or sources):
            raise JournalError("knowledge needs a source (url or source ids)")
        policy = confidence_for(kind, agreeing_sources)
        conf = policy if confidence is None else max(0.0, min(float(confidence), policy))
        ts = _now()
        with self._txn() as cur:
            cur.execute(
                "INSERT INTO knowledge(claim, kind, source_url, source_title, excerpt, confidence, basis, sources, "
                "tags, question, task_id, created, status, verified_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'ACTIVE',?)",
                (
                    claim[:2000], kind, source_url, source_title, (excerpt or "")[:2000] or None, conf,
                    basis or f"{kind}: {agreeing_sources} source(s)", _dumps(sources or []),
                    _dumps(sorted({t.lower() for t in (tags or []) if t})), question, task_id, ts,
                    None if kind == "human" else ts,
                ),
            )
            kid = int(cur.lastrowid)
            self._insert_event(
                cur, ts, task_id, "knowledge.stored",
                {"knowledge_id": kid, "kind": kind, "confidence": conf, "claim": claim[:160], "source_url": source_url, "tags": sorted({t.lower() for t in (tags or []) if t})},
            )
        return self.knowledge(kid)

    def human_facts(self, limit: int = 300) -> List[dict]:
        """Facts the human told SYRAX (kind human), oldest first; earlier versions a correction replaced
        (SUPERSEDED) are not facts any more and are left out."""
        limit = max(1, min(int(limit), 1000))
        with self._lock:
            rows = self._db.execute(
                f"SELECT * FROM knowledge WHERE kind='human' AND {self._live()} ORDER BY created DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._knowledge_dict(r) for r in reversed(rows)]

    def update_knowledge_claim_sync(self, knowledge_id: int, claim: str, task_id: Optional[str] = None,
                                    confidence: Optional[float] = None, tags: Optional[List[str]] = None,
                                    basis: Optional[str] = None) -> Optional[dict]:
        """Overwrite a row's claim and, when given, its confidence (capped by the kind's policy), tags and basis.
        The `knowledge.updated` event keeps `previous` (the old text, memory type and confidence), so an overwrite
        can be audited (memory truth, 2026-10-25). When the text changes, the old version is also kept as a row of
        its own (audit 2026-10-27, item 4: the event cut it at 160 characters): a copy of the old row, SUPERSEDED,
        superseded_by this id, named by the event's `previous_id`. The row itself keeps its id, so the memory panel
        and every reference to it still point at the current text. A SUPERSEDED row is never rewritten."""
        ts = _now()
        with self._txn() as cur:
            row = cur.execute("SELECT * FROM knowledge WHERE id=?", (knowledge_id,)).fetchone()
            if row is None:
                return None
            old = self._knowledge_dict(row)
            if old["status"] == "SUPERSEDED":
                raise JournalError(f"knowledge {knowledge_id} is SUPERSEDED by {old['superseded_by']}: it is not rewritten")
            new_tags = old["tags"] if tags is None else sorted({t.lower() for t in tags if t})
            conf = old["confidence"] if confidence is None else max(0.0, min(float(confidence), confidence_for(old["kind"])))
            previous_id = None
            if claim[:2000] != old["claim"]:
                cur.execute(
                    "INSERT INTO knowledge(claim, kind, source_url, source_title, excerpt, confidence, basis, sources, tags, "
                    "question, task_id, created, last_used, uses, status, verified_at, superseded_by) "
                    "SELECT claim, kind, source_url, source_title, excerpt, confidence, basis, sources, tags, question, task_id, "
                    "created, last_used, uses, 'SUPERSEDED', verified_at, id FROM knowledge WHERE id=?", (knowledge_id,))
                previous_id = int(cur.lastrowid)
            cur.execute("UPDATE knowledge SET claim=?, confidence=?, tags=?, basis=?, last_used=? WHERE id=?",
                        (claim[:2000], conf, _dumps(new_tags), basis or old["basis"], ts, knowledge_id))
            self._insert_event(cur, ts, task_id, "knowledge.updated", {
                "knowledge_id": knowledge_id, "kind": old["kind"], "claim": claim[:160], "type": _memory_type(new_tags), "confidence": conf,
                "previous": {"claim": old["claim"][:160], "type": _memory_type(old["tags"]), "confidence": old["confidence"]},
                "previous_id": previous_id})
        return self.knowledge(knowledge_id)

    def forget_knowledge_sync(self, ids: List[int], reason: str = "human asked", task_id: Optional[str] = None) -> List[dict]:
        """Delete knowledge rows (the human's right to be forgotten); the deletion itself is journaled. The earlier
        versions of a forgotten human fact (SUPERSEDED rows a correction left, superseded_by it) go with it, named in
        the event's `versions`: forgetting a fact forgets what it used to say."""
        gone = []
        ts = _now()
        with self._txn() as cur:
            for kid in ids:
                row = cur.execute("SELECT * FROM knowledge WHERE id=?", (int(kid),)).fetchone()
                if row is None:
                    continue
                versions, todo = [], [int(kid)] if row["kind"] == "human" else []
                while todo:
                    nxt = [r[0] for r in cur.execute(
                        f"SELECT id FROM knowledge WHERE kind='human' AND superseded_by IN ({','.join('?' * len(todo))})", todo)]
                    versions += nxt
                    todo = nxt
                cur.execute("DELETE FROM knowledge WHERE id=?", (int(kid),))
                if versions:
                    cur.execute(f"DELETE FROM knowledge WHERE id IN ({','.join('?' * len(versions))})", versions)
                gone.append(self._knowledge_dict(row))
                self._insert_event(cur, ts, task_id, "knowledge.forgotten", {"knowledge_id": int(kid), "kind": row["kind"], "claim": row["claim"][:160], "reason": reason,
                                                                             **({"versions": versions} if versions else {})})
        return gone

    # Knowledge state (audit 2026-10-27, item 4). Every change is checked against KNOWLEDGE_TRANSITIONS and journaled
    # in the same transaction; SUPERSEDED never comes back.

    def dispute_knowledge_sync(self, ids: List[int], why: str, task_id: Optional[str] = None,
                               contradiction: Optional[dict] = None) -> List[int]:
        """Mark rows DISPUTED: stored knowledge contradicts itself. `contradiction` (the knowledge.contradiction
        payload that found it) is journaled in the same transaction, so the finding and the state never part.
        `knowledge.disputed {knowledge_ids, disputed, why}` is journaled when a row changed. SUPERSEDED rows stay
        SUPERSEDED. Returns the ids that became DISPUTED."""
        ts = _now()
        changed, involved = [], []
        with self._txn() as cur:
            if contradiction is not None:
                task = self._row(cur, task_id) if task_id else None
                ev_id = self._insert_event(cur, ts, task_id, "knowledge.contradiction", dict(contradiction))
                if task is not None and ev_id is not None:
                    self._apply(cur, task, "knowledge.contradiction", contradiction, ev_id, ts)
            for kid in dict.fromkeys(int(i) for i in ids if i is not None):
                row = cur.execute("SELECT status FROM knowledge WHERE id=?", (kid,)).fetchone()
                if row is None or row["status"] == "SUPERSEDED":
                    continue
                involved.append(kid)
                if row["status"] != "DISPUTED":
                    self._knowledge_transition(row["status"], "DISPUTED")
                    cur.execute("UPDATE knowledge SET status='DISPUTED' WHERE id=?", (kid,))
                    changed.append(kid)
            if changed:
                self._insert_event(cur, ts, task_id, "knowledge.disputed", {"knowledge_ids": involved, "disputed": changed, "why": str(why)[:300]})
        return changed

    def supersede_knowledge_sync(self, losers: List[int], winner: int, why: str, evidence: Optional[list] = None,
                                 task_id: Optional[str] = None) -> List[int]:
        """Settle a dispute: `losers` become SUPERSEDED (superseded_by `winner`), the winner ACTIVE and verified now;
        journaled as `knowledge.superseded {knowledge_ids, superseded_by, why, evidence}`. A row only supersedes rows
        of its own kind (a conclusion never replaces a web excerpt or the human's word), and a SUPERSEDED row
        supersedes nothing. Returns the ids that became SUPERSEDED."""
        ts = _now()
        changed = []
        with self._txn() as cur:
            w = cur.execute("SELECT id, kind, status FROM knowledge WHERE id=?", (int(winner),)).fetchone()
            if w is None:
                raise JournalError(f"unknown knowledge {winner}")
            if w["status"] == "SUPERSEDED":
                raise JournalError(f"knowledge {winner} is SUPERSEDED: it supersedes nothing")
            for kid in dict.fromkeys(int(i) for i in losers if i is not None and int(i) != int(winner)):
                row = cur.execute("SELECT kind, status FROM knowledge WHERE id=?", (kid,)).fetchone()
                if row is None or row["status"] == "SUPERSEDED":
                    continue
                if row["kind"] != w["kind"]:
                    raise JournalError(f"knowledge {winner} ({w['kind']}) cannot supersede {kid} ({row['kind']})")
                self._knowledge_transition(row["status"], "SUPERSEDED")
                cur.execute("UPDATE knowledge SET status='SUPERSEDED', superseded_by=? WHERE id=?", (int(winner), kid))
                changed.append(kid)
            self._knowledge_transition(w["status"], "ACTIVE")
            cur.execute("UPDATE knowledge SET status='ACTIVE', verified_at=? WHERE id=?", (ts, int(winner)))
            self._insert_event(cur, ts, task_id, "knowledge.superseded", {
                "knowledge_ids": changed, "superseded_by": int(winner), "was": w["status"], "why": str(why)[:300],
                "evidence": list(evidence or [])[:10]})
        return changed

    def verify_knowledge_sync(self, knowledge_id: int, why: str = "", evidence: Optional[list] = None,
                              resolve: bool = False, task_id: Optional[str] = None) -> Optional[dict]:
        """The row was confirmed again (its page still says it, or an independent source supports it): verified_at
        = now. With `resolve`, a DISPUTED row becomes ACTIVE (`knowledge.resolved`): the caller found independent
        evidence and nothing stored contradicts it any more. A SUPERSEDED row is left as it is (None)."""
        ts = _now()
        with self._txn() as cur:
            row = cur.execute("SELECT status FROM knowledge WHERE id=?", (int(knowledge_id),)).fetchone()
            if row is None or row["status"] == "SUPERSEDED":
                return None
            cur.execute("UPDATE knowledge SET verified_at=? WHERE id=?", (ts, int(knowledge_id)))
            if resolve and row["status"] == "DISPUTED":
                self._knowledge_transition("DISPUTED", "ACTIVE")
                cur.execute("UPDATE knowledge SET status='ACTIVE' WHERE id=?", (int(knowledge_id),))
                self._insert_event(cur, ts, task_id, "knowledge.resolved",
                                   {"knowledge_id": int(knowledge_id), "why": str(why)[:300], "evidence": list(evidence or [])[:10]})
        return self.knowledge(knowledge_id)

    @staticmethod
    def _knowledge_transition(current: str, new: str) -> None:
        if current != new and new not in KNOWLEDGE_TRANSITIONS.get(current, frozenset()):
            raise JournalError(f"invalid knowledge transition {current} -> {new}")

    def knowledge(self, knowledge_id: int) -> Optional[dict]:
        """One row by id, whatever its status (a cited id, the memory panel's row): callers read `status`."""
        with self._lock:
            row = self._db.execute("SELECT * FROM knowledge WHERE id=?", (knowledge_id,)).fetchone()
        return self._knowledge_dict(row) if row else None

    def web_knowledge_like(self, source_url: str, excerpt: Optional[str]) -> Optional[dict]:
        """The oldest stored web row with this source_url and this excerpt (compared as add_knowledge_sync stores it),
        or None. Read only: `research` reinforces that row instead of storing the same page excerpt again
        (live 2026-10-26: one SQLite-history excerpt was stored 24 times)."""
        stored = (excerpt or "")[:2000] or None
        if not source_url or stored is None:
            return None
        with self._lock:
            row = self._db.execute(
                f"SELECT * FROM knowledge WHERE kind='web' AND source_url=? AND excerpt=? AND {self._live()} ORDER BY id ASC LIMIT 1",
                (source_url, stored),
            ).fetchone()
        return self._knowledge_dict(row) if row else None

    def knowledge_recent(self, limit: int = 50, since: Optional[float] = None, tag: Optional[str] = None,
                         include_superseded: bool = False) -> List[dict]:
        """The newest rows; SUPERSEDED rows only with `include_superseded` (they are history, not knowledge)."""
        limit = max(1, min(int(limit), 500))
        sql, params = "SELECT * FROM knowledge", []
        conds = [] if include_superseded else [self._live()]
        if since is not None:
            conds.append("created>=?"); params.append(since)
        if tag:
            conds.append("tags LIKE ?"); params.append(f'%"{tag.lower()}"%')
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY created DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._db.execute(sql, params).fetchall()
        return [self._knowledge_dict(r) for r in rows]

    def knowledge_of_kind(self, kinds, limit: int = 2000) -> List[dict]:
        """Rows of the given kinds (e.g. ("conclusion", "web")), oldest first, with their sources and status, SUPERSEDED
        ones included: the memory export (the record) and consolidate (which skips them itself)."""
        kinds = tuple(k for k in kinds if k in KNOWLEDGE_KINDS)
        if not kinds:
            return []
        with self._lock:
            rows = self._db.execute(
                f"SELECT * FROM knowledge WHERE kind IN ({','.join('?' * len(kinds))}) ORDER BY created ASC LIMIT ?",
                (*kinds, max(1, min(int(limit), 5000))),
            ).fetchall()
        return [self._knowledge_dict(r) for r in rows]

    def disputed_knowledge(self, limit: int = 500) -> List[dict]:
        """The DISPUTED rows, oldest first: the contradictions still open (autonomy derives a settle objective from
        them). Read only; an owner still on the old schema has no state, so nothing is disputed there."""
        if not getattr(self, "_kstate", True):
            return []
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM knowledge WHERE status='DISPUTED' ORDER BY id ASC LIMIT ?", (max(1, min(int(limit), 5000)),)
            ).fetchall()
        return [self._knowledge_dict(r) for r in rows]

    def knowledge_search(self, query: str, limit: int = 8) -> List[dict]:
        """Keyword-overlap ranking over claim, excerpt, tags and question; SUPERSEDED rows are not retrieved."""
        words = {w for w in re_words(query) if len(w) > 2}
        if not words:
            return []
        with self._lock:
            rows = self._db.execute(f"SELECT * FROM knowledge WHERE {self._live()} ORDER BY created DESC LIMIT 2000").fetchall()
        scored = []
        for r in rows:
            hay = " ".join(str(r[k] or "") for k in ("claim", "excerpt", "tags", "question")).lower()
            hits = sum(1 for w in words if w in hay)
            if hits:
                scored.append((hits / len(words), r["confidence"], r["created"], r))
        scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        out = [self._knowledge_dict(r) for _, _, _, r in scored[:limit]]
        if out:
            with self._txn() as cur:
                cur.executemany(
                    "UPDATE knowledge SET uses=uses+1, last_used=? WHERE id=?", [(_now(), k["id"]) for k in out]
                )
        return out

    # ——— benchmarks + experiments (performance is measured, never asserted) ———

    def add_benchmark_sync(self, metrics: dict, status: str, deltas: Optional[dict] = None, compared_to: Optional[int] = None,
                           git_head: Optional[str] = None, task_id: Optional[str] = None) -> dict:
        if status not in ("BASELINE", "PASS", "REGRESSION", "NOT_VERIFIED"):
            raise JournalError(f"bad benchmark status {status!r}")
        ts = _now()
        with self._txn() as cur:
            cur.execute(
                "INSERT INTO benchmarks(ts, git_head, metrics, status, compared_to, deltas, task_id) VALUES (?,?,?,?,?,?,?)",
                (ts, git_head or _git_head(self.repo_root), _dumps(metrics), status, compared_to, _dumps(deltas or {}), task_id),
            )
            bid = int(cur.lastrowid)
            self._insert_event(cur, ts, task_id, "benchmark.completed", {"benchmark_id": bid, "status": status, "compared_to": compared_to,
                                                                          "regressions": [k for k, d in (deltas or {}).items() if d.get("regression")]})
        return self.benchmark(bid)

    def benchmark(self, benchmark_id: int) -> Optional[dict]:
        with self._lock:
            row = self._db.execute("SELECT * FROM benchmarks WHERE id=?", (benchmark_id,)).fetchone()
        return self._bench_dict(row) if row else None

    def benchmarks(self, limit: int = 20) -> List[dict]:
        limit = max(1, min(int(limit), 500))
        with self._lock:
            rows = self._db.execute("SELECT * FROM benchmarks ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [self._bench_dict(r) for r in rows]

    @staticmethod
    def _bench_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["metrics"] = _loads(d.get("metrics"), {})
        d["deltas"] = _loads(d.get("deltas"), {})
        return d

    def add_quality_run_sync(self, results: list, pass_rate: float, status: str, compared_to: Optional[int] = None,
                             delta: Optional[float] = None, brain: Optional[str] = None) -> dict:
        if status not in ("BASELINE", "PASS", "REGRESSION"):
            raise JournalError(f"bad quality status {status!r}")
        ts = _now()
        with self._txn() as cur:
            cur.execute(
                "INSERT INTO quality_runs(ts, git_head, brain, results, pass_rate, status, compared_to, delta) VALUES (?,?,?,?,?,?,?,?)",
                (ts, _git_head(self.repo_root), brain, _dumps(results), float(pass_rate), status, compared_to, delta),
            )
            qid = int(cur.lastrowid)
            self._insert_event(cur, ts, None, "quality.completed", {
                "quality_id": qid, "status": status, "pass_rate": float(pass_rate), "delta": delta, "compared_to": compared_to, "brain": brain,
                "failed": [r["id"] for r in results if not r.get("ok")],
            })
        return self.quality_run(qid)

    def quality_run(self, quality_id: int) -> Optional[dict]:
        with self._lock:
            row = self._db.execute("SELECT * FROM quality_runs WHERE id=?", (quality_id,)).fetchone()
        return {**dict(row), "results": _loads(row["results"], [])} if row else None

    def quality_runs(self, limit: int = 20) -> List[dict]:
        limit = max(1, min(int(limit), 500))
        with self._lock:
            rows = self._db.execute("SELECT * FROM quality_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{**dict(r), "results": _loads(r["results"], [])} for r in rows]

    def add_experiment_sync(self, hypothesis: str, baseline: dict, candidate: dict, metric: str, result: dict, conclusion: str,
                            verdict: str, objective: Optional[str] = None, next_action: Optional[str] = None,
                            task_id: Optional[str] = None) -> dict:
        if verdict not in ("CANDIDATE_BETTER", "BASELINE_BETTER", "NO_DIFFERENCE", "INCONCLUSIVE"):
            raise JournalError(f"bad verdict {verdict!r}")
        ts = _now()
        with self._txn() as cur:
            cur.execute(
                "INSERT INTO experiments(ts, hypothesis, objective, baseline, candidate, metric, result, conclusion, verdict, next_action, task_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (ts, hypothesis, objective, _dumps(baseline), _dumps(candidate), metric, _dumps(result), conclusion, verdict, next_action, task_id),
            )
            eid = int(cur.lastrowid)
            self._insert_event(cur, ts, task_id, "experiment.completed", {"experiment_id": eid, "hypothesis": hypothesis[:160], "verdict": verdict, "metric": metric})
        return self.experiment(eid)

    # ——— the archive of SYRAX's own variants (Phase 5, DGM-style) ———

    def add_archive_sync(self, head: Optional[str], parent: Optional[str], decision: str, summary: str, objective_id: Optional[int],
                         task_id: Optional[str], experiment_id: Optional[int]) -> dict:
        ts = _now()
        with self._txn() as cur:
            cur.execute(
                "INSERT INTO archive(ts, head, parent, decision, summary, objective_id, task_id, experiment_id) VALUES (?,?,?,?,?,?,?,?)",
                (ts, head, parent, decision, summary, objective_id, task_id, experiment_id),
            )
            aid = int(cur.lastrowid)  # no event of its own: experiment.completed already marks the attempt in the task's sequence
        return self.archive_row(aid)

    def score_archive_sync(self, head: str, pass_rate: float, quality_run_id: Optional[int]) -> int:
        """A quality run measured `head`: every committed variant at that commit takes the score."""
        if not head:
            return 0
        with self._txn() as cur:
            cur.execute("UPDATE archive SET score=?, quality_run_id=? WHERE head IS NOT NULL AND (head=? OR head LIKE ?)",
                        (float(pass_rate), quality_run_id, head, head[:7] + "%"))
            return int(cur.rowcount)

    def archive_row(self, archive_id: int) -> Optional[dict]:
        with self._lock:
            row = self._db.execute("SELECT * FROM archive WHERE id=?", (archive_id,)).fetchone()
        return dict(row) if row else None

    def archive(self, limit: int = 80) -> List[dict]:
        limit = max(1, min(int(limit), 1000))
        with self._lock:
            rows = self._db.execute("SELECT * FROM archive ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def experiment(self, experiment_id: int) -> Optional[dict]:
        with self._lock:
            row = self._db.execute("SELECT * FROM experiments WHERE id=?", (experiment_id,)).fetchone()
        return self._exp_dict(row) if row else None

    def experiments(self, limit: int = 20) -> List[dict]:
        limit = max(1, min(int(limit), 500))
        with self._lock:
            rows = self._db.execute("SELECT * FROM experiments ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [self._exp_dict(r) for r in rows]

    @staticmethod
    def _exp_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        for k in ("baseline", "candidate", "result"):
            d[k] = _loads(d.get(k), {})
        return d

    # ——— skills registry ———

    @staticmethod
    def _skill_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["evidence"] = _loads(d.get("evidence"), {})
        d["dependencies"] = _loads(d.get("dependencies"), [])
        d["known_limitations"] = _loads(d.get("known_limitations"), [])
        return d

    def upsert_skill_sync(
        self,
        name: str,
        purpose: str,
        path: str,
        status: str,
        evidence: Optional[dict] = None,
        tests_passed: int = 0,
        tests_failed: int = 0,
        dependencies: Optional[List[str]] = None,
        known_limitations: Optional[List[str]] = None,
        created_task_id: Optional[str] = None,
        event: Optional[str] = None,
        content_hash: Optional[str] = None,
    ) -> dict:
        """`version` counts verifications (every call bumps it). `code_version` counts code: it moves only when
        `content_hash` differs from the stored one (skills.content_hash: sha256 over the skill's .py files); a row
        that has no hash yet takes the first one it is given without a bump, and a call without a hash keeps both."""
        if status not in SKILL_STATUSES:
            raise JournalError(f"bad skill status {status!r}")
        ts = _now()
        with self._txn() as cur:
            row = cur.execute("SELECT version, content_hash, code_version FROM skills WHERE name=?", (name,)).fetchone()
            version = (int(row["version"]) + 1) if row else 1
            code_version = int(row["code_version"] or 1) if row else 1
            if row and content_hash and row["content_hash"] and row["content_hash"] != content_hash:
                code_version += 1
            content_hash = content_hash or (row["content_hash"] if row else None)
            cur.execute(
                "INSERT INTO skills(name, version, purpose, path, status, tests_passed, tests_failed, evidence, "
                "dependencies, known_limitations, created_task_id, created, updated, last_verified, content_hash, code_version) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET version=excluded.version, "
                "purpose=excluded.purpose, path=excluded.path, status=excluded.status, tests_passed=excluded.tests_passed, "
                "tests_failed=excluded.tests_failed, evidence=excluded.evidence, dependencies=excluded.dependencies, "
                "known_limitations=excluded.known_limitations, updated=excluded.updated, last_verified=excluded.last_verified, "
                "content_hash=excluded.content_hash, code_version=excluded.code_version",
                (
                    name, version, purpose, path, status, tests_passed, tests_failed, _dumps(evidence or {}),
                    _dumps(dependencies or []), _dumps(known_limitations or []), created_task_id, ts, ts,
                    ts if status == "VERIFIED" else None, content_hash, code_version,
                ),
            )
            self._insert_event(
                cur, ts, created_task_id, event or f"skill.{status.lower()}",
                {"skill": name, "version": version, "status": status, "tests_passed": tests_passed, "tests_failed": tests_failed, "purpose": purpose[:160],
                 "content_hash": content_hash, "code_version": code_version},
            )
        return self.skill(name)

    def set_skill_status_sync(self, name: str, status: str, note: Optional[str] = None, task_id: Optional[str] = None) -> dict:
        if status not in SKILL_STATUSES:
            raise JournalError(f"bad skill status {status!r}")
        ts = _now()
        with self._txn() as cur:
            row = cur.execute("SELECT content_hash, code_version FROM skills WHERE name=?", (name,)).fetchone()
            if not row:
                raise JournalError(f"unknown skill {name}")
            cur.execute("UPDATE skills SET status=?, updated=? WHERE name=?", (status, ts, name))
            self._insert_event(cur, ts, task_id, f"skill.{status.lower()}",
                               {"skill": name, "status": status, "note": note, "content_hash": row["content_hash"], "code_version": row["code_version"]})
        return self.skill(name)

    def backfill_skill_hash_sync(self, name: str, content_hash: Optional[str]) -> bool:
        """Store `content_hash` for a skill row that has none (verified before skills carried one, 2026-10-25, and
        not re-verified since), touching neither `version` nor `code_version`: the code on disk is the code that was
        verified, and from here its next change is counted. True when a hash was stored."""
        if not content_hash:
            return False
        with self._txn() as cur:
            n = cur.execute("UPDATE skills SET content_hash=? WHERE name=? AND (content_hash IS NULL OR content_hash='')",
                            (content_hash, name)).rowcount
        return bool(n)

    def skill(self, name: str) -> Optional[dict]:
        with self._lock:
            row = self._db.execute("SELECT * FROM skills WHERE name=?", (name,)).fetchone()
        return self._skill_dict(row) if row else None

    def skills(self, status: Optional[str] = None) -> List[dict]:
        sql, params = "SELECT * FROM skills", []
        if status:
            sql += " WHERE status=?"; params.append(status)
        sql += " ORDER BY name"
        with self._lock:
            rows = self._db.execute(sql, params).fetchall()
        return [self._skill_dict(r) for r in rows]

    # ——— maintenance (retention) ———

    def maintain(self, retain_days: float = 30.0, now: Optional[float] = None) -> dict:
        """Bounded growth without losing the record: for tasks that ended more
        than ``retain_days`` ago, drop chatty ``think``/``brain.*`` events and
        the saved checkpoint context; keep task rows, tool/final/checkpoint
        events and evidence. Then truncate the WAL. Returns measured counts."""
        now = now or _now()
        cutoff = now - retain_days * 86400
        before = self.path.stat().st_size if self.path.exists() else None
        with self._txn() as cur:
            old = [
                r[0] for r in cur.execute(
                    "SELECT task_id FROM tasks WHERE status IN ('SUCCESS','PARTIAL','FAILED','CANCELLED','UNKNOWN') AND updated<?",
                    (cutoff,),
                ).fetchall()
            ]
            pruned = trimmed = 0
            for tid in old:
                cur.execute(
                    "DELETE FROM events WHERE task_id=? AND type IN ('think','brain.failover','brain.answered',"
                    "'presentation.created','presentation.dismissed')", (tid,)
                )
                pruned += cur.rowcount
                cur.execute("UPDATE checkpoints SET context='[]' WHERE task_id=? AND context<>'[]'", (tid,))
                trimmed += cur.rowcount
            cur.execute(
                "DELETE FROM events WHERE task_id IS NULL AND type IN ('presentation.created','presentation.dismissed') AND ts<?",
                (cutoff,),
            )
            pruned += cur.rowcount
            self._insert_event(
                cur, now, None, "maintenance.completed",
                {"tasks_examined": len(old), "events_pruned": pruned, "checkpoint_contexts_trimmed": trimmed, "retain_days": retain_days},
            )
            cur.execute("INSERT INTO meta(key, value) VALUES ('last_maintenance', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(now),))
        with self._lock:
            wal = self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        after = self.path.stat().st_size if self.path.exists() else None
        return {
            "tasks_examined": len(old), "events_pruned": pruned, "checkpoint_contexts_trimmed": trimmed,
            "wal_checkpoint": list(wal) if wal else None, "bytes_before": before, "bytes_after": after,
        }

    def maintenance_due(self, every_s: float = 86400.0, now: Optional[float] = None) -> bool:
        last = self.get_meta("last_maintenance")
        if last is None:
            return True
        try:
            return (now or _now()) - float(last) >= every_s
        except ValueError:
            return True

    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._txn() as cur:
            cur.execute("INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    # ——— queries ———

    @staticmethod
    def _task_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["operation"] = _loads(d.get("operation"))
        d["recovery"] = _loads(d.get("recovery"))
        return d

    def task(self, task_id: str) -> Optional[dict]:
        with self._lock:
            row = self._db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        return self._task_dict(row) if row else None

    def tasks(self, limit: int = 20, status: Optional[str | Iterable[str]] = None) -> List[dict]:
        limit = max(1, min(int(limit), 500))
        sql = "SELECT * FROM tasks"
        params: list = []
        if status:
            statuses = [status] if isinstance(status, str) else list(status)
            sql += f" WHERE status IN ({','.join('?' * len(statuses))})"
            params += statuses
        sql += " ORDER BY created DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._db.execute(sql, params).fetchall()
        return [self._task_dict(r) for r in rows]

    def events(self, task_id: str, limit: int = 500, after_id: int = 0) -> List[dict]:
        limit = max(1, min(int(limit), 5000))
        with self._lock:
            rows = self._db.execute(
                "SELECT id, ts, task_id, type, payload, seq FROM events "
                "WHERE task_id=? AND id>? ORDER BY seq LIMIT ?",
                (task_id, after_id, limit),
            ).fetchall()
        return [{**dict(r), "payload": _loads(r["payload"], {})} for r in rows]

    def last_event_id(self) -> int:
        with self._lock:
            return int(self._db.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0])

    def events_since(self, event_id: int, limit: int = 1000) -> List[Event]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, ts, task_id, type, payload, seq FROM events WHERE id>? ORDER BY id LIMIT ?",
                (event_id, limit),
            ).fetchall()
        return [Event(r["id"], r["ts"], r["task_id"], r["type"], r["seq"], _loads(r["payload"], {})) for r in rows]

    def events_of_type(self, type_: str, since: float = 0.0, limit: int = 500) -> List[dict]:
        """The newest `limit` events of one type since `since`, oldest first."""
        limit = max(1, min(int(limit), 5000))
        with self._lock:
            rows = self._db.execute(
                "SELECT id, ts, task_id, type, payload, seq FROM events WHERE type=? AND ts>=? ORDER BY id DESC LIMIT ?",
                (type_, since, limit),
            ).fetchall()
        return [{**dict(r), "payload": _loads(r["payload"], {})} for r in reversed(rows)]

    def events_between(self, ts_from: float, ts_to: Optional[float] = None, limit: int = 2000) -> List[dict]:
        """All events (task-bound and task-less) in a time window, oldest first.
        This is what a daily replay is generated from; nothing is synthesised."""
        limit = max(1, min(int(limit), 10000))
        ts_to = ts_to if ts_to is not None else _now()
        with self._lock:
            rows = self._db.execute(
                "SELECT id, ts, task_id, type, payload, seq FROM events WHERE ts>=? AND ts<=? ORDER BY id LIMIT ?",
                (ts_from, ts_to, limit),
            ).fetchall()
        return [{**dict(r), "payload": _loads(r["payload"], {})} for r in rows]

    def task_detail(self, task_id: str) -> Optional[dict]:
        """Everything the journal knows about one task: the WHY view."""
        task = self.task(task_id)
        if task is None:
            return None
        with self._lock:
            obj = self._db.execute(
                "SELECT * FROM objectives WHERE last_task_id=? ORDER BY updated DESC LIMIT 1", (task_id,)
            ).fetchone()
        return {
            "task": task,
            "events": self.events(task_id),
            "checkpoints": [
                {k: v for k, v in cp.items() if k != "context"} | {"context_messages": len(cp.get("context") or [])}
                for cp in self.checkpoints(task_id)
            ],
            "objective": self._objective_dict(obj) if obj else None,
        }

    def recent_exchanges(self, n: int = 6) -> List[dict]:
        """The last finished conversations (goal + reply), oldest first: the
        journal is the source of truth that history.jsonl used to duplicate."""
        n = max(1, min(int(n), 50))
        with self._lock:
            rows = self._db.execute(
                "SELECT goal, result, updated FROM tasks WHERE kind='conversation' AND status IN ('SUCCESS','PARTIAL') "
                "AND result IS NOT NULL AND result<>'' ORDER BY created DESC LIMIT ?", (n,),
            ).fetchall()
        return [{"ts": r["updated"], "user": r["goal"], "reply": r["result"]} for r in reversed(rows)]

    def presentation_stats(self, since: Optional[float] = None) -> Dict[str, dict]:
        """Per kind: how many elements were shown, how many a human dismissed and how fast,
        how many expired or were replaced. Evidence for the presentation engine's preferences."""
        with self._lock:
            rows = self._db.execute(
                "SELECT type, payload FROM events WHERE type IN ('presentation.created','presentation.feedback','presentation.dismissed') "
                + ("AND ts>=? " if since else "") + "ORDER BY id",
                ((since,) if since else ()),
            ).fetchall()
        out: Dict[str, dict] = {}
        for r in rows:
            p = _loads(r["payload"], {})
            kind = p.get("kind") or "?"
            st = out.setdefault(kind, {"shown": 0, "human_dismissed": 0, "dismiss_after_s": [], "expired": 0, "task_ended": 0})
            if r["type"] == "presentation.created":
                st["shown"] += 1
            elif r["type"] == "presentation.feedback" and p.get("action") == "dismiss":
                st["human_dismissed"] += 1
                if isinstance(p.get("after_s"), (int, float)):
                    st["dismiss_after_s"].append(float(p["after_s"]))
            elif r["type"] == "presentation.dismissed":
                if p.get("reason") == "expired":
                    st["expired"] += 1
                elif p.get("reason") == "task ended":
                    st["task_ended"] += 1
        for st in out.values():
            xs = sorted(st.pop("dismiss_after_s"))
            st["median_dismiss_after_s"] = (xs[len(xs) // 2] if xs else None)
        return out

    def answered_by(self) -> Dict[str, Dict[str, int]]:
        """{task_id: {provider: answers}} over the whole journal (brain scorecard)."""
        with self._lock:
            rows = self._db.execute(
                "SELECT task_id, json_extract(payload, '$.provider') AS p, COUNT(*) AS n FROM events "
                "WHERE type='brain.answered' AND task_id IS NOT NULL GROUP BY task_id, p"
            ).fetchall()
        out: Dict[str, Dict[str, int]] = {}
        for r in rows:
            if r["p"]:
                out.setdefault(r["task_id"], {})[r["p"]] = int(r["n"])
        return out

    def recent_events(self, limit: int = 100) -> List[dict]:
        limit = max(1, min(int(limit), 5000))
        with self._lock:
            rows = self._db.execute(
                "SELECT id, ts, task_id, type, payload, seq FROM events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [{**dict(r), "payload": _loads(r["payload"], {})} for r in reversed(rows)]

    def checkpoints(self, task_id: str) -> List[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM checkpoints WHERE task_id=? ORDER BY seq", (task_id,)
            ).fetchall()
        return [self._cp_dict(r) for r in rows]

    def latest_checkpoint(self, task_id: str) -> Optional[dict]:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM checkpoints WHERE task_id=? ORDER BY seq DESC LIMIT 1", (task_id,)
            ).fetchone()
        return self._cp_dict(row) if row else None

    @staticmethod
    def _cp_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        for k in ("completed_steps", "current_operation", "verified", "assumptions", "env", "context"):
            d[k] = _loads(d.get(k))
        return d

    def verifications(self, limit: int = 20) -> List[dict]:
        limit = max(1, min(int(limit), 500))
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM verifications ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [{**dict(r), "gates": _loads(r["gates"], [])} for r in rows]

    def status_counts(self) -> Dict[str, int]:
        with self._lock:
            rows = self._db.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status").fetchall()
        return {r[0]: int(r[1]) for r in rows}

    def tool_stats(self) -> Dict[str, dict]:
        """Per-tool evidence from events: uses, failures, last use, last failure,
        last outcome. Derived, never hand-written. A call a guard refused (tool.failed
        with refused) is no use and no failure of the tool, only counted as refused:
        live 2026-10-15 a refused os.remove in python_execute made the tool FAILING and
        the cycle spent a task on "python_execute failed, diagnose why"."""
        with self._lock:
            rows = self._db.execute(
                "SELECT type, ts, task_id, json_extract(payload, '$.name') AS name, json_extract(payload, '$.id') AS cid, "
                "json_extract(payload, '$.refused') AS refused, "
                "CASE WHEN type='tool.failed' THEN substr(json_extract(payload, '$.output'), 1, 400) END AS output FROM events "
                "WHERE type IN ('tool.started','tool.completed','tool.failed') AND name IS NOT NULL "
                "ORDER BY id"
            ).fetchall()
        out: Dict[str, dict] = {}
        started: Dict[tuple, tuple] = {}
        for r in rows:
            st = out.setdefault(
                r["name"],
                {"uses": 0, "successes": 0, "failures": 0, "refused": 0, "misuse": 0, "last_used": None, "last_failed": None, "last_outcome": None},
            )
            if r["type"] == "tool.started":
                started[(r["task_id"], r["cid"])] = (st["last_used"], r["ts"])
                st["uses"] += 1
                st["last_used"] = r["ts"]
            elif r["type"] == "tool.failed" and r["refused"]:
                prev, ts = started.pop((r["task_id"], r["cid"]), (st["last_used"], None))
                st["uses"] -= ts is not None
                st["refused"] += 1
                if ts is not None and st["last_used"] == ts:  # a refused call is no use of the tool
                    st["last_used"] = prev
            elif r["type"] == "tool.completed":
                st["successes"] += 1
                st["last_outcome"] = "ok"
            else:
                st["failures"] += 1
                st["last_failed"] = r["ts"]
                st["last_outcome"] = "misuse" if misuse(r["name"], r["output"]) else "fail"
                st["misuse"] += st["last_outcome"] == "misuse"
        return out

    def count(self, table: str) -> int:
        if table not in ("events", "tasks", "checkpoints", "verifications", "objectives", "knowledge", "skills", "benchmarks", "experiments", "quality_runs"):
            raise ValueError(table)
        with self._lock:
            return int(self._db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def pragma(self, name: str) -> Any:
        with self._lock:
            return self._db.execute(f"PRAGMA {name}").fetchone()[0]

    def backup_to(self, path: Path | str) -> int:
        """Copy the whole journal into a new SQLite file at `path` with the online backup API (syrax.backup).
        The copy reads through a connection of its own, read-only, in one backup step: one read transaction,
        so under WAL it is one consistent snapshot of what was committed, and writes go on beside it. It held
        the journal lock for the whole copy (~150 MB) instead, and every sync read on the event loop (task(),
        events(), get_meta()) waits on that lock: the daily backup froze the loop. Outside WAL a reader would
        block writers, so there the lock is still held as before. The copy is turned into a plain
        rollback-journal file, so nothing (-wal, -shm) has to travel with it. A read-only handle can copy too:
        that is how `python -m syrax.backup --snapshot` works beside a running SYRAX. Returns the copy's size."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(f"file:{self.path.resolve().as_posix()}?mode=ro", uri=True, timeout=10)
        try:
            dst = sqlite3.connect(str(path))
            try:
                if str(src.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal":
                    src.backup(dst)  # pages=-1: every page in one step, one snapshot
                else:
                    with self._lock:
                        src.backup(dst)
                dst.execute("PRAGMA journal_mode=DELETE")
            finally:
                dst.close()
        finally:
            src.close()
        return path.stat().st_size

    def close(self) -> None:
        global _journal
        with self._lock:
            try:
                self._db.close()
            except sqlite3.Error:
                pass
        if self._owner:
            _unlock_owner(self.path)
            self._owner = False
        if _journal is self:
            _journal = None  # a later get_journal() reopens instead of using a dead handle

    # ——— async facade + fan-out ———

    def subscribe(self, cb: Subscriber) -> None:
        if cb not in self._subs:
            self._subs.append(cb)

    def unsubscribe(self, cb: Subscriber) -> None:
        if cb in self._subs:
            self._subs.remove(cb)

    async def _fanout(self, ev: Optional[Event]) -> None:
        if ev is None:
            return
        for cb in list(self._subs):
            try:
                await cb(ev)
            except Exception as e:  # observers must never break the journal
                log.warning("journal subscriber failed: %s", e)

    async def run(self, fn: Callable[..., Any], *args, **kwargs) -> Any:
        """Run a sync journal call in a worker thread, then fan out every event
        it committed. Use this for objective/meta writes from async code.

        Only the events that call inserted: it fanned out every id after the one it began at, so the events other
        coroutines committed meanwhile (already fanned out by their own record()) went out twice during a slow call
        (derive_objectives, backup.snapshot): duplicate UI lines, a reminder.fired spoken twice."""

        def call() -> Any:
            self._mine.ids = ids = []
            try:
                return fn(*args, **kwargs), ids
            finally:
                self._mine.ids = None

        result, ids = await asyncio.to_thread(call)
        for ev in self._events_by_id(ids):
            await self._fanout(ev)
        return result

    def _events_by_id(self, ids: List[int]) -> List[Event]:
        """The committed events among `ids`, in id order (a rolled-back insert's id is not there, or is reused)."""
        out: List[Event] = []
        ids = sorted(set(ids))
        for i in range(0, len(ids), 500):
            part = ids[i:i + 500]
            with self._lock:
                rows = self._db.execute(
                    f"SELECT id, ts, task_id, type, payload, seq FROM events WHERE id IN ({','.join('?' * len(part))}) ORDER BY id",
                    part,
                ).fetchall()
            out += [Event(r["id"], r["ts"], r["task_id"], r["type"], r["seq"], _loads(r["payload"], {})) for r in rows]
        return out

    async def add_objective(self, *args, **kwargs) -> Optional[dict]:
        return await self.run(self.add_objective_sync, *args, **kwargs)

    async def update_objective(self, *args, **kwargs) -> dict:
        return await self.run(self.update_objective_sync, *args, **kwargs)

    async def start_task(self, goal: str, session_id: Optional[str] = None, kind: str = "conversation", pending: bool = False) -> str:
        task_id = await asyncio.to_thread(self.start_task_sync, goal, session_id, kind, pending)
        first = self.events(task_id, limit=1)
        if first:
            e = first[0]
            await self._fanout(Event(e["id"], e["ts"], task_id, e["type"], e["seq"], e["payload"]))
        return task_id

    async def record(
        self,
        type_: str,
        payload: Optional[dict] = None,
        task_id: Optional[str] = None,
        volatile: Optional[dict] = None,
        dedupe_key: Optional[str] = None,
    ) -> Optional[Event]:
        ev = await asyncio.to_thread(self.record_sync, type_, payload, task_id, volatile, dedupe_key)
        await self._fanout(ev)
        return ev

    async def checkpoint(self, task_id: str, stage: str, **kw) -> Event:
        ev = await asyncio.to_thread(lambda: self.checkpoint_sync(task_id, stage, **kw))
        await self._fanout(ev)
        return ev

    async def mark_resumed(self, task_id: str, session_id: Optional[str] = None) -> Event:
        ev = await asyncio.to_thread(self.mark_resumed_sync, task_id, session_id)
        await self._fanout(ev)
        return ev

    async def record_verification(self, result: dict, task_id: Optional[str] = None) -> Event:
        ev = await asyncio.to_thread(self.record_verification_sync, result, task_id)
        await self._fanout(ev)
        return ev

    async def recover(self, resume: Optional[ResumeHook] = None) -> List[dict]:
        reports = await asyncio.to_thread(self.recover_interrupted)
        self.recovered = self.recovered + reports
        if resume is not None:
            for r in reports:
                try:
                    await resume(r)
                except Exception as e:
                    log.warning("resume hook failed for %s: %s", r["task_id"], e)
        return reports


class _Txn:
    """BEGIN IMMEDIATE ... COMMIT under the journal lock; ROLLBACK on error."""

    def __init__(self, journal: Journal):
        self.j = journal
        self.cur: Optional[sqlite3.Cursor] = None

    def __enter__(self) -> sqlite3.Cursor:
        if getattr(self.j, "read_only", False):
            raise JournalError(
                f"journal {self.j.path} is read-only here: a running SYRAX process owns it and is the only one "
                "that records tasks, evidence and quality runs"
            )
        self.j._lock.acquire()
        try:
            self.cur = self.j._db.cursor()
            self.cur.execute("BEGIN IMMEDIATE")
        except BaseException:
            self.j._lock.release()
            raise
        mine = getattr(self.j._mine, "ids", None)
        self._mark = len(mine) if mine is not None else None
        return self.cur

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self.j._db.execute("COMMIT")
            else:
                try:
                    self.j._db.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                self._forget_rolled_back()
        except BaseException:
            self._forget_rolled_back()  # a failed COMMIT rolled back as well
            raise
        finally:
            self.j._lock.release()

    def _forget_rolled_back(self) -> None:
        """Journal.run fans out the ids its thread inserted: a rolled-back insert's id may be reused by another
        writer's event, which that writer fans out itself."""
        mine = getattr(self.j._mine, "ids", None)
        if mine is not None and self._mark is not None:
            del mine[self._mark:]


def _bound_context(messages: list) -> list:
    """Keep the message list under MAX_CONTEXT_CHARS, newest first, without
    splitting a tool-call/result pair from its assistant message."""
    out: List[dict] = []
    size = 0
    for m in messages:
        if not isinstance(m, dict):
            continue
        m = dict(m)
        m.pop("base64_image", None)
        if isinstance(m.get("content"), str) and len(m["content"]) > MAX_MESSAGE_CHARS:
            m["content"] = m["content"][:MAX_MESSAGE_CHARS] + "…[truncated]"
        out.append(m)
        size += len(_dumps(m))
    while out and size > MAX_CONTEXT_CHARS:
        dropped = out.pop(0)
        size -= len(_dumps(dropped))
        # never leave orphan tool results at the head
        while out and out[0].get("role") == "tool":
            size -= len(_dumps(out.pop(0)))
    return out


_journal: Optional[Journal] = None


def get_journal() -> Journal:
    global _journal
    if _journal is None:
        _journal = Journal(os.getenv("SYRAX_JOURNAL_FILE", str(DEFAULT_FILE)))
    return _journal
