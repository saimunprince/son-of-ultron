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
import sqlite3
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional

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
TERMINAL_OK = frozenset({"verification.completed", "reflection.created", "knowledge.stored"})

# Tools whose side effects can be verified against the filesystem after a crash.
CHECKABLE_TOOLS = frozenset({"str_replace_editor"})

MAX_CONTEXT_CHARS = 200_000
MAX_MESSAGE_CHARS = 8_000


class JournalError(RuntimeError):
    """A write was refused because it would make the journal lie."""


def _now() -> float:
    return time.time()


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


def _git_head(cwd: Path) -> Optional[str]:
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
_GROUPED = ("task", "recovery", "brain", "objective", "cycle", "reflection", "autonomy", "knowledge", "research")


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
  uses         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS knowledge_created ON knowledge(created);
"""

KNOWLEDGE_KINDS = ("web", "local", "experiment", "human", "conclusion")
# Confidence policy: evidence decides, never the author.
CONFIDENCE_CEILING = {"web": 0.75, "local": 0.9, "experiment": 0.95, "human": 1.0, "conclusion": 0.9}


def confidence_for(kind: str, agreeing_sources: int = 1) -> float:
    if kind == "web":
        return {1: 0.4, 2: 0.6}.get(max(1, agreeing_sources), 0.75)
    return CONFIDENCE_CEILING.get(kind, 0.4)

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
        self.recovered: List[dict] = []
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(
            str(self.path), check_same_thread=False, isolation_level=None, timeout=10
        )
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(_DDL)
        self._db.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        if recover:
            self.recovered = self.recover_interrupted()

    # ——— helpers ———

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
        return int(cur.lastrowid)

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
        if evidence_state not in EVIDENCE_STATES:
            raise JournalError(f"bad evidence_state {evidence_state!r}")
        ts = _now()
        ctx = _bound_context(context or [])
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

    def verify_operation(self, op: Optional[dict]) -> dict:
        """Compare a persisted in-flight operation with reality.

        Returns {"state": COMPLETED|NOT_STARTED|PARTIAL|UNCERTAIN|NONE, "checks": {...}}.
        Only filesystem edits are checkable; anything else is UNCERTAIN.
        """
        if not op:
            return {"state": "NONE", "checks": {}}
        name = str(op.get("name") or "")
        args = op.get("args") if isinstance(op.get("args"), dict) else {}
        if name == "ask_human":
            return {"state": "BLOCKED", "checks": {"question": args.get("inquire")}}
        if name not in CHECKABLE_TOOLS:
            return {"state": "UNCERTAIN", "checks": {"reason": f"{name} side effects cannot be inspected"}}
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
            text = path.read_text(errors="replace")
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
        verdict = self.verify_operation(op)
        op_state = verdict["state"]
        if row["status"] == "BLOCKED" or op_state == "BLOCKED":
            state = "BLOCKED"
        elif op_state in ("NONE", "COMPLETED", "NOT_STARTED"):
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

    def objective(self, objective_id: int) -> Optional[dict]:
        with self._lock:
            row = self._db.execute("SELECT * FROM objectives WHERE id=?", (objective_id,)).fetchone()
        return self._objective_dict(row) if row else None

    def objectives(self, limit: int = 50, status: Optional[str | Iterable[str]] = None) -> List[dict]:
        limit = max(1, min(int(limit), 500))
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

    # ——— knowledge (provenance-aware) ———

    @staticmethod
    def _knowledge_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["sources"] = _loads(d.get("sources"), [])
        d["tags"] = _loads(d.get("tags"), [])
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
        kind; a caller may lower it, never raise it above the policy."""
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
                "tags, question, task_id, created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    claim[:2000], kind, source_url, source_title, (excerpt or "")[:2000] or None, conf,
                    basis or f"{kind}: {agreeing_sources} source(s)", _dumps(sources or []),
                    _dumps(sorted({t.lower() for t in (tags or []) if t})), question, task_id, ts,
                ),
            )
            kid = int(cur.lastrowid)
            self._insert_event(
                cur, ts, task_id, "knowledge.stored",
                {"knowledge_id": kid, "kind": kind, "confidence": conf, "claim": claim[:160], "source_url": source_url, "tags": sorted({t.lower() for t in (tags or []) if t})},
            )
        return self.knowledge(kid)

    def knowledge(self, knowledge_id: int) -> Optional[dict]:
        with self._lock:
            row = self._db.execute("SELECT * FROM knowledge WHERE id=?", (knowledge_id,)).fetchone()
        return self._knowledge_dict(row) if row else None

    def knowledge_recent(self, limit: int = 50, since: Optional[float] = None, tag: Optional[str] = None) -> List[dict]:
        limit = max(1, min(int(limit), 500))
        sql, params = "SELECT * FROM knowledge", []
        conds = []
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

    def knowledge_search(self, query: str, limit: int = 8) -> List[dict]:
        """Keyword-overlap ranking over claim, excerpt, tags and question."""
        words = {w for w in re_words(query) if len(w) > 2}
        if not words:
            return []
        with self._lock:
            rows = self._db.execute("SELECT * FROM knowledge ORDER BY created DESC LIMIT 2000").fetchall()
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
        last outcome. Derived, never hand-written."""
        with self._lock:
            rows = self._db.execute(
                "SELECT type, ts, json_extract(payload, '$.name') AS name FROM events "
                "WHERE type IN ('tool.started','tool.completed','tool.failed') AND name IS NOT NULL "
                "ORDER BY id"
            ).fetchall()
        out: Dict[str, dict] = {}
        for r in rows:
            st = out.setdefault(
                r["name"],
                {"uses": 0, "successes": 0, "failures": 0, "last_used": None, "last_failed": None, "last_outcome": None},
            )
            if r["type"] == "tool.started":
                st["uses"] += 1
                st["last_used"] = r["ts"]
            elif r["type"] == "tool.completed":
                st["successes"] += 1
                st["last_outcome"] = "ok"
            else:
                st["failures"] += 1
                st["last_failed"] = r["ts"]
                st["last_outcome"] = "fail"
        return out

    def count(self, table: str) -> int:
        if table not in ("events", "tasks", "checkpoints", "verifications", "objectives", "knowledge"):
            raise ValueError(table)
        with self._lock:
            return int(self._db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def pragma(self, name: str) -> Any:
        with self._lock:
            return self._db.execute(f"PRAGMA {name}").fetchone()[0]

    def close(self) -> None:
        global _journal
        with self._lock:
            try:
                self._db.close()
            except sqlite3.Error:
                pass
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
        it committed. Use this for objective/meta writes from async code."""
        before = self.last_event_id()
        result = await asyncio.to_thread(lambda: fn(*args, **kwargs))
        for ev in self.events_since(before):
            await self._fanout(ev)
        return result

    async def add_objective(self, *args, **kwargs) -> Optional[dict]:
        return await self.run(self.add_objective_sync, *args, **kwargs)

    async def update_objective(self, *args, **kwargs) -> dict:
        return await self.run(self.update_objective_sync, *args, **kwargs)

    async def start_task(self, goal: str, session_id: Optional[str] = None, kind: str = "conversation") -> str:
        task_id = await asyncio.to_thread(self.start_task_sync, goal, session_id, kind)
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
        self.j._lock.acquire()
        try:
            self.cur = self.j._db.cursor()
            self.cur.execute("BEGIN IMMEDIATE")
        except BaseException:
            self.j._lock.release()
            raise
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
        finally:
            self.j._lock.release()


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
