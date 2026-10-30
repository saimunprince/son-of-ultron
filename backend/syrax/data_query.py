"""data_query: ask questions of a CSV/TSV or SQLite file with read-only SQL, or profile its data quality.

EVOLUTION_PLAN directions 225 (database reasoning) and 246 (data-quality assessment): SYRAX could read only its own
journal with SQL; a human's spreadsheet export or database meant guessing through python_execute. A CSV/TSV is loaded
into an in-memory SQLite table named `data`; a SQLite file opens read-only (mode=ro). One SELECT/WITH runs, at most
MAX_ROWS rows come back. Without sql the file is profiled: rows, per column the guessed type, empty cells, distinct
values, min and max, and duplicate rows. SYRAX's own config folder (keys, journal) is never read here."""

from __future__ import annotations

import csv
import re
import sqlite3
from pathlib import Path
from typing import Any, List, Optional

from app.tool.base import BaseTool, ToolResult

MAX_ROWS = 50
MAX_CELL = 200
MAX_LOAD_ROWS = 200_000
MAX_BYTES = 100 * 2**20
_READ_ONLY = re.compile(r"^\s*(select|with)\b", re.I)
_FORBIDDEN = re.compile(r"\b(insert|update|delete|replace|drop|alter|create|attach|detach|pragma|vacuum|reindex)\b", re.I)


def _sealed(path: Path) -> bool:
    from syrax.journal import BACKEND_ROOT

    try:
        return path.resolve().is_relative_to((BACKEND_ROOT / "config").resolve())
    except OSError:
        return True


def _column(name: str, seen: set) -> str:
    base = re.sub(r"\W+", "_", name.strip()).strip("_") or "col"
    if base[0].isdigit():
        base = "c_" + base
    out, n = base, 2
    while out.lower() in seen:
        out, n = f"{base}_{n}", n + 1
    seen.add(out.lower())
    return out


def open_data(path: str) -> sqlite3.Connection:
    """A read-only connection: the SQLite file itself, or a CSV/TSV loaded into table `data`."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise ValueError(f"no file at {p}")
    if _sealed(p):
        raise ValueError("SYRAX's own config folder (keys, journal) is never read with data_query")
    if p.stat().st_size > MAX_BYTES:
        raise ValueError(f"{p.name} is larger than {MAX_BYTES // 2**20} MB")
    with open(p, "rb") as f:
        head = f.read(16)
    if head.startswith(b"SQLite format 3"):
        return sqlite3.connect(f"file:{p.resolve().as_posix()}?mode=ro", uri=True)
    with open(p, newline="", encoding="utf-8-sig", errors="replace") as f:
        sample = f.read(65536)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel_tab if p.suffix.lower() == ".tsv" else csv.excel
        rows = csv.reader(f, dialect)
        header = next(rows, None)
        if not header:
            raise ValueError(f"{p.name} is empty or not a CSV/TSV")
        seen: set = set()
        cols = [_column(h, seen) for h in header]
        db = sqlite3.connect(":memory:")
        db.execute(f"CREATE TABLE data ({', '.join(f'[{c}]' for c in cols)})")
        batch = []
        for i, r in enumerate(rows):
            if i >= MAX_LOAD_ROWS:
                break
            r = (r + [""] * len(cols))[: len(cols)]
            batch.append([v if v != "" else None for v in r])
        db.executemany(f"INSERT INTO data VALUES ({', '.join('?' * len(cols))})", batch)
        db.commit()
        return db


def query(path: str, sql: str) -> str:
    sql = (sql or "").strip().rstrip(";")
    if not _READ_ONLY.match(sql) or _FORBIDDEN.search(sql) or ";" in sql:
        raise ValueError("only one read-only SELECT/WITH statement")
    db = open_data(path)
    try:
        cur = db.execute(sql)
        names = [d[0] for d in cur.description or []]
        rows = cur.fetchmany(MAX_ROWS + 1)
    finally:
        db.close()
    more = len(rows) > MAX_ROWS
    lines = [" | ".join(names)] + [" | ".join(str(v)[:MAX_CELL] for v in r) for r in rows[:MAX_ROWS]]
    return "\n".join(lines) + (f"\n(first {MAX_ROWS} rows shown)" if more else f"\n({len(rows)} row(s))")


def _type_of(values: List[str]) -> str:
    def all_match(fn) -> bool:
        try:
            for v in values:
                fn(v)
            return True
        except ValueError:
            return False

    if not values:
        return "empty"
    if all_match(int):
        return "integer"
    if all_match(float):
        return "number"
    if all(re.match(r"^\d{4}-\d\d-\d\d", v) for v in values):
        return "date"
    return "text"


def profile(path: str) -> str:
    """The data-quality report of the file's first table (`data` for a CSV)."""
    db = open_data(path)
    try:
        table = db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchone()
        if not table:
            raise ValueError("no table in this file")
        t = table[0]
        cols = [r[1] for r in db.execute(f"PRAGMA table_info([{t}])")]
        n = db.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
        dup = db.execute(f"SELECT COALESCE(SUM(c - 1), 0) FROM (SELECT COUNT(*) c FROM [{t}] GROUP BY {', '.join(f'[{c}]' for c in cols)})").fetchone()[0]
        lines = [f"PROFILE of {Path(path).name}: table {t}, {n} rows, {len(cols)} columns, {dup} duplicate row(s)"]
        for c in cols:
            empty = db.execute(f"SELECT COUNT(*) FROM [{t}] WHERE [{c}] IS NULL OR TRIM(CAST([{c}] AS TEXT)) = ''").fetchone()[0]
            distinct = db.execute(f"SELECT COUNT(DISTINCT [{c}]) FROM [{t}]").fetchone()[0]
            values = [str(r[0]) for r in db.execute(f"SELECT [{c}] FROM [{t}] WHERE [{c}] IS NOT NULL LIMIT 1000")]
            kind = _type_of([v for v in values if v.strip()])
            span = ""
            if kind in ("integer", "number"):
                lo, hi = db.execute(f"SELECT MIN(CAST([{c}] AS REAL)), MAX(CAST([{c}] AS REAL)) FROM [{t}] WHERE TRIM(CAST([{c}] AS TEXT)) != ''").fetchone()
                span = f", min {lo:g}, max {hi:g}"
            lines.append(f"- {c}: {kind}, {empty} empty ({(100 * empty / n if n else 0):.0f}%), {distinct} distinct{span}")
    finally:
        db.close()
    return "\n".join(lines)


class DataQueryTool(BaseTool):
    name: str = "data_query"
    description: str = (
        "Read a CSV/TSV or SQLite file: without sql, a data-quality profile (rows, column types, empty cells, distinct "
        "values, min/max, duplicate rows); with sql, one read-only SELECT (at most 50 rows). A CSV is the table `data`; "
        "column names are its header with spaces turned into _."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path of the .csv, .tsv, .sqlite or .db file."},
            "sql": {"type": "string", "description": "One SELECT/WITH statement; leave out for the profile."},
        },
        "required": ["path"],
    }

    async def execute(self, path: str = "", sql: str = "", **_: Any) -> ToolResult:
        import asyncio

        try:
            out = await asyncio.to_thread(query if (sql or "").strip() else profile, path, *([sql] if (sql or "").strip() else []))
            return ToolResult(output=out)
        except (ValueError, sqlite3.Error, OSError) as e:
            return ToolResult(error=f"data_query: {e}")
