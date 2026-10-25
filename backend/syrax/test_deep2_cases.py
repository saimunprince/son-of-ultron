"""Deep quality cases, second tier (2026-10-25): run #64 passed the nine deep cases 9/9 in 4.5 minutes, so that tier
no longer showed a weakness and the repro hunts again had nothing to work on. Each deep2 case is a longer piece of real
work judged by running the result. Here every case is shown solvable (a reference solution passes every outcome check),
and not passable by doing nothing or by the shortcut its data is built to catch."""

import csv
import json
import re
import sys
from pathlib import Path

import pytest

from syrax import quality

ENV = {"git_short": "abc1234", "cpu_count": "8", "python_mm": f"{sys.version_info.major}.{sys.version_info.minor}"}
DEEP2 = ("deep2_refactor_module", "deep2_data_pipeline", "deep2_fix_flaky", "deep2_cli_subcommands", "deep2_log_report",
         "deep2_spec_from_tests")


def deep2(tmp_path, case_id):
    ws = tmp_path / "ws"
    case = next(c for c in quality._cases(ws) if c["id"] == case_id)
    quality.prepare(case, ws)
    return case, ws / "deep2"


def failed(case, final=""):
    return [c["check"] for c in quality.check_case(case, {"status": "SUCCESS", "result": final}, [], ENV) if not c["ok"]]


def test_the_deep2_cases_are_in_the_suite_with_more_room_than_the_deep_ones(tmp_path):
    cases = {c["id"]: c for c in quality._cases(tmp_path)}
    assert set(DEEP2) <= set(cases) and len(cases) == 67
    assert all(cases[i]["timeout"] == quality.DEEP2_TIMEOUT_S > quality.DEEP_TIMEOUT_S for i in DEEP2)
    known = {"command_regex", "file_regex", "file_equals", "no_ask", "no_promise"}  # judged by running the result, never by its words
    assert {ch["kind"] for i in DEEP2 for ch in cases[i]["checks"]} <= known


@pytest.mark.parametrize("case_id", DEEP2)
def test_doing_nothing_fails_every_deep2_case(tmp_path, case_id):
    case, _ = deep2(tmp_path, case_id)
    assert failed(case)


TEXTUTIL = 'def clean_name(text):\n    return " ".join(w.capitalize() for w in text.split())\n'


def test_refactor_module(tmp_path):
    case, d = deep2(tmp_path, "deep2_refactor_module")
    pkg = d / "refactor" / "pkg"
    # the shortcut: both copies corrected in place, nothing shared
    (pkg / "users.py").write_text(TEXTUTIL + "\n\ndef display_name(user):\n    return clean_name(user[\"name\"])\n")
    (pkg / "orders.py").write_text(TEXTUTIL + "\n\ndef customer_label(order):\n    return f\"{clean_name(order['customer'])} #{order['id']}\"\n")
    assert failed(case)
    # the other shortcut: one of the two buggy copies promoted to the shared module as it is
    (pkg / "users.py").write_text("from pkg.textutil import clean_name\n\n\ndef display_name(user):\n    return clean_name(user[\"name\"])\n")
    (pkg / "orders.py").write_text("from pkg.textutil import clean_name\n\n\ndef customer_label(order):\n"
                                   "    return f\"{clean_name(order['customer'])} #{order['id']}\"\n")
    (pkg / "textutil.py").write_text(quality.DEEP2_USERS.split("\n\n\n")[0] + "\n")  # keeps inner whitespace
    assert failed(case)
    (pkg / "textutil.py").write_text(quality.DEEP2_ORDERS.split("\n\n\n")[0] + "\n")  # keeps the case of the rest of a word
    assert failed(case)
    (pkg / "textutil.py").write_text(TEXTUTIL)
    assert failed(case, "clean_name lives in pkg/textutil.py now; users.py and orders.py import it.") == []
    (d / "_accept" / "test_refactor_shared.py").write_text("def test_nothing():\n    assert True\n")  # the acceptance tests are not the model's to edit
    assert failed(case, "Done.")


def pipeline_report(d, dedupe=True, trim=True):
    pipe = d / "pipeline"
    strip = (lambda s: s.strip()) if trim else (lambda s: s)
    names = {strip(r["customer_id"]): r["name"] for r in csv.DictReader((pipe / "customers.csv").open())}
    prices = {strip(r["product_id"]): float(r["price"].replace("$", "")) for r in csv.DictReader((pipe / "products.csv").open())}
    revenue, skipped, seen = {}, {"duplicate_order": 0, "unknown_customer": 0}, set()
    for r in csv.DictReader((pipe / "orders.csv").open()):
        if dedupe and r["order_id"] in seen:
            skipped["duplicate_order"] += 1
            continue
        seen.add(r["order_id"])
        cust = strip(r["customer_id"])
        if cust not in names:
            skipped["unknown_customer"] += 1
            continue
        revenue[names[cust]] = revenue.get(names[cust], 0.0) + int(r["qty"]) * prices[strip(r["product_id"])]
    rows = [{"customer": n, "revenue": round(v, 2)} for n, v in sorted(revenue.items(), key=lambda kv: -kv[1])]
    (pipe / "report.json").write_text(json.dumps({"revenue": rows, "skipped": skipped}, indent=2))
    return rows


def test_data_pipeline(tmp_path):
    case, d = deep2(tmp_path, "deep2_data_pipeline")
    assert [(r["customer"], r["revenue"]) for r in pipeline_report(d)] == [("Ana", 35.0), ("Bo", 32.5), ("Cy", 10.5)]
    assert failed(case, "report.json written: Ana 35.00, Bo 32.50, Cy 10.50; 2 rows skipped.") == []
    assert pipeline_report(d, dedupe=False)[0] == {"customer": "Bo", "revenue": 45.0}  # the duplicate counted twice puts Bo first
    assert failed(case)
    with pytest.raises(KeyError):  # the untrimmed " 2" and "p3 " never match
        pipeline_report(d, trim=False)
    with pytest.raises(ValueError):  # the naive float("$12.50")
        float(next(r["price"] for r in csv.DictReader((d / "pipeline" / "products.csv").open()) if r["product_id"] == "p2"))
    (d / "pipeline" / "report.json").write_text(json.dumps({"revenue": [{"customer": "Ana", "revenue": 35.0}, {"customer": "Bo", "revenue": 32.5},
                                                                        {"customer": "Cy", "revenue": 10.5}], "skipped": {"duplicate_order": 1, "unknown_customer": 1}}))
    assert failed(case, "Done.") == []  # the exact numbers are what is judged, not the route


TALLY_FIXED = ("def summary(words):\n    uniq = sorted(set(words))\n    return f\"{len(uniq)} unique: {', '.join(uniq)}\"\n")


def test_fix_flaky(tmp_path):
    case, d = deep2(tmp_path, "deep2_fix_flaky")
    flaky = d / "flaky"
    (flaky / "tally.py").write_text(TALLY_FIXED)
    assert failed(case, "tally.py sorts the words and no longer samples the wording; 5/5 runs green.") == []
    # the shortcut: the time-dependent branch removed but the set still iterated as it comes (a new order every process)
    (flaky / "tally.py").write_text(TALLY_FIXED.replace("sorted(set(words))", "set(words)"))
    assert failed(case)
    # the other half: the words sorted but the sampled wording kept; five runs in a row pass one time in 3**5
    (flaky / "tally.py").write_text(quality.DEEP2_TALLY.replace("set(words)", "sorted(set(words))"))
    assert failed(case) or failed(case)
    (flaky / "tally.py").write_text(TALLY_FIXED)
    (flaky / "test_tally.py").write_text("def test_summary():\n    assert True\n")  # the test is not the model's to change
    assert failed(case, "Green.")


INVENTORY = '''import json
import sys
from pathlib import Path

STORE = Path(__file__).with_name("inventory.json")


def load():
    return json.loads(STORE.read_text()) if STORE.exists() else {}


def main(argv):
    stock = load()
    if argv[0] == "list":
        for name in sorted(stock):
            print(f"{name}: {stock[name]}")
        return 0
    name, qty = argv[1], int(argv[2])
    if argv[0] == "add":
        stock[name] = stock.get(name, 0) + qty
    elif argv[0] == "remove":
        if stock.get(name, 0) < qty:
            print(f"cannot remove {qty} {name}: only {stock.get(name, 0)} on hand")
            return 2
        stock[name] -= qty
    STORE.write_text(json.dumps(stock))
    return 0


sys.exit(main(sys.argv[1:]))
'''


def test_cli_subcommands(tmp_path):
    case, d = deep2(tmp_path, "deep2_cli_subcommands")
    inv = d / "inventory"
    inv.mkdir(parents=True, exist_ok=True)
    (inv / "inventory.py").write_text(INVENTORY)
    assert failed(case, "inventory.py built; add, remove and list work, inventory.json holds the stock.") == []
    # the shortcut: removing more than on hand is reported but exits 0
    (inv / "inventory.py").write_text(INVENTORY.replace("            return 2\n", "            return 0\n"))
    assert failed(case)
    # the other shortcut: the removal goes through (stock negative or clamped), with the right exit code
    (inv / "inventory.py").write_text(INVENTORY.replace("            return 2\n", "            stock[name] = 0\n            STORE.write_text(json.dumps(stock))\n            return 2\n"))
    assert failed(case)
    (inv / "inventory.py").write_text(INVENTORY.replace("for name in sorted(stock):", "for name in reversed(sorted(stock)):"))
    assert failed(case)  # the list is sorted by name


def log_report(d, level_field=True, all_levels=True):
    stats = {}
    for line in (d / "logs" / "app.log").read_text().splitlines():
        ts, level, rid, msg = re.match(r"(\S+ \S+) (\w+) \[(\S+)\] (.*)", line).groups()
        s = stats.setdefault(rid, {"first": ts, "errors": 0, "slowest": ("", 0)})
        s["last"] = ts
        s["errors"] += (level == "ERROR") if level_field else ("ERROR" in line)
        m = re.search(r"step (\w+) took (\d+) ms", msg)
        if m and (all_levels or level == "INFO") and int(m.group(2)) > s["slowest"][1]:
            s["slowest"] = (m.group(1), int(m.group(2)))
    out = []
    for rid, s in sorted(stats.items()):
        out += [f"## {rid}", "", "| metric | value |", "|---|---|", f"| first | {s['first']} |", f"| last | {s['last']} |",
                f"| errors | {s['errors']} |", f"| slowest | {s['slowest'][0]} {s['slowest'][1]} ms |", ""]
    (d / "logs" / "report.md").write_text("\n".join(out))
    return stats


def test_log_report(tmp_path):
    case, d = deep2(tmp_path, "deep2_log_report")
    stats = log_report(d)
    assert [(r, s["errors"], s["slowest"]) for r, s in sorted(stats.items())] == [("req-a1", 3, ("retry", 880)), ("req-b2", 5, ("render", 640)), ("req-c3", 2, ("pay", 1200))]
    assert failed(case, "report.md written with a table per request id.") == []
    grep = log_report(d, level_field=False)  # the shortcut: every line that says ERROR, WARN lines about errors included
    assert [s["errors"] for _, s in sorted(grep.items())] == [4, 6, 3]
    assert failed(case)
    info_only = log_report(d, all_levels=False)  # the other shortcut: durations read from INFO lines only
    assert info_only["req-a1"]["slowest"] != ("retry", 880) and info_only["req-c3"]["slowest"] != ("pay", 1200)
    assert failed(case)


SLUGIFY = '''import re
import unicodedata


def slugify(text):
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    if len(slug) > 40:
        cut = slug.rfind("-", 0, 41)
        slug = slug[:cut] if cut > 0 else slug[:40]
    return slug or "n-a"
'''


def test_spec_from_tests(tmp_path):
    case, d = deep2(tmp_path, "deep2_spec_from_tests")
    slug = d / "slug"
    slug.mkdir(parents=True, exist_ok=True)
    (slug / "test_slugify.py").write_text("from slugify import slugify\n\n\ndef test_basic():\n    assert slugify('Hello World') == 'hello-world'\n")
    # the shortcut: the slug cut at 40 characters, mid-word
    (slug / "slugify.py").write_text(SLUGIFY.replace("        cut = slug.rfind(\"-\", 0, 41)\n        slug = slug[:cut] if cut > 0 else slug[:40]\n",
                                                     "        slug = slug[:40].strip(\"-\")\n"))
    assert failed(case)  # its own test passes; the hidden boundary case does not
    (slug / "slugify.py").write_text(SLUGIFY)
    assert failed(case, "slugify.py and its tests pass.") == []
    (d / "_accept" / "test_slugify_accept.py").write_text("def test_nothing():\n    assert True\n")
    assert failed(case, "Green.")
