"""The harder cases (2026-10-13, after the first 16/16 run): each passes only
on the real outcome. fix_bug needs the tests passing and the tests untouched,
find_fact needs the hidden code, research_report needs a cited file and a
working research call."""

import sys

from syrax.quality import BUGGY_STATS, STATS_TESTS, _cases, check_case


def cases(ws):
    return {c["id"]: c for c in _cases(ws)}


def prepared(ws, cid):
    c = cases(ws)[cid]
    for path, text in c["prepare"].get("write", {}).items():
        from pathlib import Path

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text)
    return c


def test_fix_bug_needs_green_tests_and_untouched_tests(tmp_path):
    c = prepared(tmp_path, "fix_bug")
    done = {"status": "SUCCESS", "result": "Fixed mean: it divided by len - 1."}
    assert not check_case(c, done, [], {})[0]["ok"]  # the bug is really there
    (tmp_path / "bugfix" / "stats.py").write_text(BUGGY_STATS.replace("(len(xs) - 1)", "len(xs)"))
    assert all(r["ok"] for r in check_case(c, done, [], {}))
    (tmp_path / "bugfix" / "test_stats.py").write_text(STATS_TESTS.replace("== 4", "== 6"))  # weakening a test fails the case
    assert not all(r["ok"] for r in check_case(c, done, [], {}))


def test_find_fact_and_research_report_judge_the_outcome(tmp_path):
    c = prepared(tmp_path, "find_fact")
    assert (tmp_path / "haystack" / "2026" / "q4" / "team" / "notes_tuesday.txt").exists()
    assert all(r["ok"] for r in check_case(c, {"status": "SUCCESS", "result": "The code is 7341."}, [], {}))
    assert not all(r["ok"] for r in check_case(c, {"status": "SUCCESS", "result": "I could not find it."}, [], {}))
    r = cases(tmp_path)["research_report"]
    (tmp_path / "report").mkdir()
    (tmp_path / "report" / "ethanol.md").write_text("Ethanol boils at 78.37 \u00b0C at sea level. Source: https://en.wikipedia.org/wiki/Ethanol\n", encoding="utf-8")
    ev = [{"type": "tool.started", "payload": {"name": "research"}}, {"type": "tool.completed", "payload": {"name": "research"}}]
    assert all(x["ok"] for x in check_case(r, {"status": "SUCCESS", "result": "Written."}, ev, {}))
    assert not all(x["ok"] for x in check_case(r, {"status": "SUCCESS", "result": "Written."}, [], {}))  # no research, no pass
    assert sys.executable
