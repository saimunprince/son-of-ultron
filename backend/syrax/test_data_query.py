"""EVOLUTION_PLAN directions 225 (database reasoning) and 246 (data-quality assessment): SYRAX could query only its own
journal; a human's CSV export or SQLite database meant guessing through python_execute. data_query answers one
read-only SELECT over a CSV/TSV (as table `data`) or a SQLite file, or profiles the data's quality. SYRAX's own config
folder is never read with it."""

import asyncio
import sqlite3

import pytest

from syrax import data_query as Q
from syrax.journal import BACKEND_ROOT

CSV = "Name,Age,City,Joined On\nRahim,31,Dhaka,2026-01-04\nKarim,,Dhaka,2026-02-11\nRahim,31,Dhaka,2026-01-04\nSadia,27,Chittagong,2026-03-20\n"


@pytest.fixture
def csv_file(tmp_path):
    p = tmp_path / "people.csv"
    p.write_text(CSV, encoding="utf-8")
    return p


def test_a_select_over_a_csv(csv_file):
    out = Q.query(str(csv_file), "SELECT City, COUNT(*) n FROM data GROUP BY City ORDER BY n DESC")
    assert out.splitlines()[:3] == ["City | n", "Dhaka | 3", "Chittagong | 1"]
    assert "Joined_On" in Q.query(str(csv_file), "SELECT * FROM data LIMIT 1").splitlines()[0]


def test_the_profile_names_types_empties_and_duplicates(csv_file):
    out = Q.profile(str(csv_file))
    assert "4 rows, 4 columns, 1 duplicate row(s)" in out
    assert "- Age: integer, 1 empty (25%), 2 distinct, min 27, max 31" in out
    assert "- Joined_On: date" in out and "- City: text" in out


def test_a_sqlite_file_is_read_only(tmp_path):
    db = tmp_path / "shop.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE sales (item TEXT, qty INT)")
    c.executemany("INSERT INTO sales VALUES (?, ?)", [("pen", 3), ("ink", 1)])
    c.commit()
    c.close()
    assert "pen | 3" in Q.query(str(db), "SELECT * FROM sales ORDER BY qty DESC")
    for bad in ("DELETE FROM sales", "SELECT 1; DROP TABLE sales", "PRAGMA table_info(sales)"):
        with pytest.raises(ValueError, match="read-only"):
            Q.query(str(db), bad)
    assert "2 rows" in Q.profile(str(db))


def test_syrax_s_own_config_is_never_read(tmp_path):
    with pytest.raises(ValueError, match="never read"):
        Q.open_data(str(BACKEND_ROOT / "config" / "config.toml"))


def test_the_tool_reports_errors_instead_of_raising(csv_file):
    out = asyncio.run(Q.DataQueryTool().execute(path=str(csv_file)))
    assert out.output.startswith("PROFILE of people.csv")
    bad = asyncio.run(Q.DataQueryTool().execute(path="/nope/x.csv"))
    assert bad.error and "no file at" in bad.error
