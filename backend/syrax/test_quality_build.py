"""project_builder: the build_cli case runs the deliverable the way the human
would (live 2026-10-13: a built package's tests passed while its CLI failed
with ModuleNotFoundError), and a leftover project never passes it."""

import sys

from syrax.prompt import SYRAX_PERSONA
from syrax.quality import _cases, check_case


def case(ws):
    return {c["id"]: c for c in _cases(ws)}["build_cli"]


def make(root, main):
    (root / "calc").mkdir(parents=True)
    (root / "calc" / "__init__.py").write_text("")
    (root / "calc" / "ops.py").write_text("def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n")
    (root / "main.py").write_text(main)


GOOD = ("import sys\nfrom calc.ops import add, sub\nop, a, b = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])\n"
        "r = {'add': add, 'sub': sub}[op](a, b)\nprint(int(r) if r == int(r) else r)\n")
BROKEN = "from calcx.ops import add\nprint(add(2, 3))\n"  # the kind of import that failed live


def test_a_working_cli_passes_and_a_broken_one_fails(tmp_path):
    c = case(tmp_path)
    make(tmp_path / "calc_project", GOOD)
    res = check_case(c, {"status": "SUCCESS", "result": "Built it: 2 + 3 = 5."}, [], {})
    assert all(r["ok"] for r in res), res
    broken = tmp_path / "b"
    c2 = case(broken)
    make(broken / "calc_project", BROKEN)
    res = check_case(c2, {"status": "SUCCESS", "result": "4 tests passed."}, [], {})
    assert not res[0]["ok"] and "ModuleNotFoundError" in res[0]["detail"]


def test_the_case_clears_an_old_project_and_the_prompt_asks_for_proof(tmp_path):
    c = case(tmp_path)
    assert c["prepare"]["clear"] == [str(tmp_path / "calc_project")]
    assert c["checks"][0]["cmd"][0] == "{python}" and sys.executable
    assert "Prove what you build: run it exactly the way the human will use it" in SYRAX_PERSONA
