"""Deep quality cases (2026-10-22): runs #54-#61 passed 90-100 %, so the suite showed little to improve and the
repro hunts had no failures to work on. Each deep case is several steps of real work judged by running the
result. Here every case is shown solvable (a reference solution passes every outcome check), and not passable
by doing nothing or by the shortcut its data is built to catch."""

import csv
import json
import re
import sys
from pathlib import Path

import pytest

from syrax import quality

ENV = {"git_short": "abc1234", "cpu_count": "8", "python_mm": f"{sys.version_info.major}.{sys.version_info.minor}"}
DEEP = ("deep_two_bugs", "deep_todo_table", "deep_csv_join", "deep_log_triage", "deep_cli_todo", "deep_spec_tests",
        "deep_rename_api", "deep_find_largest", "deep_json_csv")


def deep(tmp_path, case_id):
    ws = tmp_path / "ws"
    case = next(c for c in quality._cases(ws) if c["id"] == case_id)
    quality.prepare(case, ws)
    return case, ws / "deep"


def failed(case, final=""):
    return [c["check"] for c in quality.check_case(case, {"status": "SUCCESS", "result": final}, [], ENV) if not c["ok"]]


def test_the_deep_cases_are_in_the_suite_with_room_to_work(tmp_path):
    cases = {c["id"]: c for c in quality._cases(tmp_path)}
    assert set(DEEP) <= set(cases)
    assert all(cases[i]["timeout"] > quality.CASE_TIMEOUT_S for i in DEEP)


@pytest.mark.parametrize("case_id", DEEP)
def test_doing_nothing_fails_every_deep_case(tmp_path, case_id):
    case, _ = deep(tmp_path, case_id)
    assert failed(case)


def test_two_bugs(tmp_path):
    case, d = deep(tmp_path, "deep_two_bugs")
    pricing = d / "shop" / "inv" / "pricing.py"
    pricing.write_text(pricing.read_text().replace("price * pct / 100", "price * (100 - pct) / 100"))
    assert failed(case)  # one bug fixed is not enough
    stock = d / "shop" / "inv" / "stock.py"
    stock.write_text(stock.read_text().replace("on_hand < minimum", "on_hand <= minimum"))
    assert failed(case, "Fixed both: the discount and the reorder test at the minimum.") == []
    (d / "shop" / "tests" / "test_stock.py").write_text("def test_nothing():\n    assert True\n")  # changing the tests is not a fix
    assert failed(case, "Fixed.")


def test_todo_table(tmp_path):
    case, d = deep(tmp_path, "deep_todo_table")
    src, out = d / "todos" / "src", d / "todos" / "todo_table.md"
    rows = []
    for path in sorted(src.rglob("*.py"), key=lambda p: p.relative_to(src).as_posix()):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            m = re.search(r"#\s*TODO:\s*(.*)", line)
            if m:
                rows.append(f"| {path.relative_to(src).as_posix()} | {n} | {m.group(1).strip()} |")
    out.write_text("| file | line | todo |\n|---|---|---|\n" + "\n".join(rows) + "\n")
    assert failed(case, f"Wrote {len(rows)} rows.") == []
    # the shortcut: every line that says TODO, in every file
    grep = [f"| {p.relative_to(src).as_posix()} | {n} | {line.strip()} |" for p in sorted(src.rglob("*")) if p.is_file()
            for n, line in enumerate(p.read_text().splitlines(), 1) if "TODO" in line]
    out.write_text("| file | line | todo |\n|---|---|---|\n" + "\n".join(grep) + "\n")
    assert failed(case)


def test_csv_join(tmp_path):
    case, d = deep(tmp_path, "deep_csv_join")
    sales = d / "sales"
    names = {r["id"]: r["name"] for r in csv.DictReader((sales / "customers.csv").open())}
    totals, counts = {}, {}
    for r in csv.DictReader((sales / "orders.csv").open()):
        totals[r["customer_id"]] = totals.get(r["customer_id"], 0) + float(r["amount"])
        counts[r["customer_id"]] = counts.get(r["customer_id"], 0) + 1
    best = max(totals, key=totals.get)
    (sales / "top.txt").write_text(f"{names[best]},{totals[best]:.2f}\n")
    assert failed(case, "Dana spent the most.") == []
    busiest = max(counts, key=counts.get)  # the shortcut: the customer with the most orders
    (sales / "top.txt").write_text(f"{names[busiest]},{totals[busiest]:.2f}\n")
    assert failed(case)


def test_log_triage(tmp_path):
    case, d = deep(tmp_path, "deep_log_triage")
    text = (d / "logs" / "app.log").read_text()
    on_error = {}
    for line in text.splitlines():
        if " ERROR " in line:
            code = re.search(r"\bE\d{3}\b", line).group(0)
            on_error[code] = on_error.get(code, 0) + 1
    code = max(on_error, key=on_error.get)
    assert failed(case, f"{code} {on_error[code]}") == []
    anywhere = {c: len(re.findall(rf"\b{c}\b", text)) for c in on_error}  # the shortcut: the code anywhere in the file
    shortcut = max(anywhere, key=anywhere.get)
    assert shortcut != code
    assert failed(case, f"{shortcut} {anywhere[shortcut]}")


TODO_APP = '''import json
import sys
from pathlib import Path

STORE = Path(__file__).with_name("todo.json")


def load():
    return json.loads(STORE.read_text()) if STORE.exists() else []


def main(argv):
    items = load()
    if argv[0] == "add":
        items.append(" ".join(argv[1:]))
    elif argv[0] == "done":
        items.pop(int(argv[1]) - 1)
    elif argv[0] == "list":
        for n, item in enumerate(items, 1):
            print(f"{n}. {item}")
        return
    STORE.write_text(json.dumps(items))


main(sys.argv[1:])
'''


def test_cli_todo(tmp_path):
    case, d = deep(tmp_path, "deep_cli_todo")
    (d / "todo_app").mkdir(parents=True, exist_ok=True)
    (d / "todo_app" / "todo.py").write_text(TODO_APP.replace("STORE.write_text(json.dumps(items))", "pass"))
    assert failed(case)  # nothing persists between two calls
    (d / "todo_app" / "todo.py").write_text(TODO_APP)
    assert failed(case, "Built todo.py.") == []


DURATIONS = '''import re

PATTERN = re.compile(r"(?:(\\d+)h)?(?:(\\d+)m)?(?:(\\d+)s)?")


def parse_duration(text):
    m = PATTERN.fullmatch(text)
    if not text or not m:
        raise ValueError(text)
    h, mi, s = (int(g or 0) for g in m.groups())
    return h * 3600 + mi * 60 + s
'''


def test_spec_tests(tmp_path):
    case, d = deep(tmp_path, "deep_spec_tests")
    dur = d / "dur"
    dur.mkdir(parents=True, exist_ok=True)
    (dur / "durations.py").write_text(DURATIONS.replace("if not text or not m", "if not m"))  # '' returns 0
    (dur / "test_durations.py").write_text("from durations import parse_duration\n\n\ndef test_minutes():\n    assert parse_duration('2m') == 120\n")
    assert failed(case)  # its own test passes; the spec's hidden ones do not
    (dur / "durations.py").write_text(DURATIONS)
    assert failed(case, "durations.py and its tests pass.") == []


def test_rename_api(tmp_path):
    case, d = deep(tmp_path, "deep_rename_api")
    geo = d / "geo_proj" / "geo"
    (geo / "core.py").write_text("def compute_area(w, h):\n    return w * h\n\n\ncalc_area = compute_area\n\n\n"
                                 "def calc_perimeter(w, h):\n    return 2 * (w + h)\n")
    assert failed(case)  # report.py still calls the old name
    (geo / "report.py").write_text((geo / "report.py").read_text().replace("calc_area", "compute_area"))
    assert failed(case, "Renamed; calc_area stays as an alias.") == []
    (geo / "core.py").write_text("def compute_area(w, h):\n    return w * h\n\n\ndef calc_perimeter(w, h):\n    return 2 * (w + h)\n")
    assert failed(case)  # old callers break without the alias


def test_find_largest(tmp_path):
    case, d = deep(tmp_path, "deep_find_largest")
    root = d / "sizes"
    files = sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: p.stat().st_size, reverse=True)
    (d / "sizes_top3.txt").write_text("\n".join(p.relative_to(root).as_posix() for p in files[:3]) + "\n")
    assert failed(case, "Done: three paths written.") == []
    (d / "sizes_top3.txt").write_text("\n".join(str(p.relative_to(root)).replace("/", "\\") for p in files[:3]) + "\n")
    assert failed(case)  # backslashes were not asked for


def test_json_csv(tmp_path):
    case, d = deep(tmp_path, "deep_json_csv")
    users = sorted(json.loads((d / "users" / "users.json").read_text()), key=lambda u: u["id"])
    with (d / "users" / "users.csv").open("w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["id", "name", "city", "roles"])
        for u in users:
            w.writerow([u["id"], u["name"], u["address"]["city"], ";".join(u["roles"])])
    assert failed(case, "Wrote users.csv.") == []
    # csv.writer's \r\n through a text-mode file on Windows: every row is followed by an empty one
    body = "".join(f"{line}\r\r\n" for line in (d / "users" / "users.csv").read_text().splitlines())
    (d / "users" / "users.csv").write_bytes(body.encode())
    assert failed(case)
