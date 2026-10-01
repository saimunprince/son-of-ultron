"""journal_query: SYRAX reads its own journal with SQL, read-only.

Live 2026-10-01: half of python_execute's failures were SYRAX guessing its
journal schema in raw sqlite3 ("no such table: tool_calls", "no such column:
id"). Knowing itself is part of its job, so instead of blocking the need this
tool serves it: the real schema is in the description, the connection is
read-only (SQLite mode=ro), only SELECT/WITH run, and at most 50 rows return.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Optional

from app.tool.base import BaseTool, ToolResult

MAX_ROWS = 50
MAX_CELL = 400
_READ_ONLY = re.compile(r"^\s*(select|with)\b", re.I)
_FORBIDDEN = re.compile(r"\b(insert|update|delete|replace|drop|alter|create|attach|detach|pragma|vacuum|reindex)\b", re.I)


def _journal_path() -> Path:
    from syrax.journal import get_journal

    return Path(get_journal().path)


def schema_text(path: Optional[Path] = None) -> str:
    """table(col, col, ...) for every table, from the database itself."""
    try:
        con = sqlite3.connect(f"file:{Path(path or _journal_path()).resolve().as_posix()}?mode=ro", uri=True)
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        parts = [f"{t}({', '.join(r[1] for r in con.execute(f'PRAGMA table_info({t})'))})" for t in tables]
        con.close()
        return "; ".join(parts)
    except sqlite3.Error:
        return "(schema unavailable)"


def run_query(sql: str, path: Optional[Path] = None) -> str:
    if not _READ_ONLY.match(sql or "") or _FORBIDDEN.search(sql or "") or ";" in sql.strip().rstrip(";"):
        raise ValueError("only one read-only SELECT/WITH statement is allowed")
    con = sqlite3.connect(f"file:{Path(path or _journal_path()).resolve().as_posix()}?mode=ro", uri=True)
    try:
        cur = con.execute(sql.strip().rstrip(";"))
        cols = [d[0] for d in cur.description or []]
        rows = cur.fetchmany(MAX_ROWS + 1)
    finally:
        con.close()
    out = []
    for row in rows[:MAX_ROWS]:
        out.append(json.dumps({c: (v if not isinstance(v, str) or len(v) <= MAX_CELL else v[:MAX_CELL] + "…") for c, v in zip(cols, row)},
                              ensure_ascii=False, default=str))
    more = f"\n(more than {MAX_ROWS} rows; add LIMIT or narrow the WHERE)" if len(rows) > MAX_ROWS else ""
    return (f"{len(out)} row(s)\n" + "\n".join(out) + more) if out else "0 rows"


class JournalQueryTool(BaseTool):
    name: str = "journal_query"
    description: str = (
        "Read your own journal with one SQL SELECT (read-only, at most 50 rows). Use it instead of "
        "python/sqlite to study your tasks, events, failures, objectives, knowledge and quality runs. "
        "Event payloads are JSON: use json_extract(payload, '$.name'). Timestamps are Unix seconds. "
        "Tables: tasks(task_id, goal, kind, status, stage, current_step, created, updated, result, error, ...); "
        "events(id, ts, task_id, type, payload, seq); objectives(id, key, goal, status, check_spec, evidence, attempts, created, updated, ...); "
        "quality_runs(id, ts, git_head, brain, results, pass_rate, status); knowledge(...); checkpoints(...); verifications(...). "
        "Call with sql='schema' for every column."
    )
    parameters: dict = {
        "type": "object",
        "properties": {"sql": {"type": "string", "description": "One SELECT/WITH statement, or 'schema'."}},
        "required": ["sql"],
    }

    async def execute(self, sql: str = "", **_: Any) -> ToolResult:
        if (sql or "").strip().lower() == "schema":
            return ToolResult(output=schema_text())
        try:
            return ToolResult(output=run_query(sql))
        except (ValueError, sqlite3.Error) as e:
            return ToolResult(error=f"{e}. Schema: {schema_text()}")
