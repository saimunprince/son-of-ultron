"""Audit 2026-11-01 (self-improvement, F1-F3, confirmed in a scratch tree): a release could pass the gate while existing
tests no longer ran. (1) A new test module patched pytest at import: `_pytest.python.Function.runtest = lambda self:
None` made a failing existing test pass. (2) A new backend/syrax/pytest.ini (`addopts = -k "not test_b"`) deselected
tests. (3) A new package backend/syrax/verify/__init__.py shadows the judge verify.py on import. Each is refused."""

import pytest

from syrax import devloop

GOOD = '''"""A normal new test."""
import json

from syrax import claims

LIMIT = 3


def helper(x):
    return x + 1


def test_it(monkeypatch, tmp_path):
    monkeypatch.setattr(claims, "DISPUTE_MAX", 5)
    assert helper(1) == 2 and json.loads("1") == 1
'''


def tree(tmp_path, rel, text):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return {rel: "??"}


def test_a_normal_new_test_is_accepted(tmp_path):
    assert devloop.tamper_problems(tmp_path, tree(tmp_path, "backend/syrax/test_new_ok.py", GOOD)) == []
    path_setup = "import sys; sys.path.insert(0, '.')\nfrom syrax.mod import VALUE\n\ndef test_v():\n    assert VALUE == 2\n"
    assert devloop.tamper_problems(tmp_path, tree(tmp_path, "backend/syrax/test_mod.py", path_setup)) == []
    assert devloop.tamper_problems(tmp_path, tree(tmp_path, "backend/syrax/test_m2.py", "import sys\nsys.path.insert(0, x)\n"))


@pytest.mark.parametrize("text, why", [
    ("import _pytest.python as _p\n_p.Function.runtest = lambda self: None\n\ndef test_x():\n    assert True\n", "_pytest"),
    ("import pytest\npytest.fail = print\n\ndef test_x():\n    assert True\n", "changes pytest"),
    ("import builtins\n\ndef test_x():\n    builtins.open = None\n    assert True\n", "changes builtins"),
    ("import os\nos.environ['X'] = '1'\n\ndef test_x():\n    assert True\n", "runs code at import"),
    ("import pytest\nsetattr(pytest, 'skip', print)\n\ndef test_x():\n    assert True\n", "runs code at import"),
])
def test_a_new_test_that_tampers_with_the_test_run_is_refused(tmp_path, text, why):
    out = devloop.tamper_problems(tmp_path, tree(tmp_path, "backend/syrax/test_0new.py", text))
    assert out and why in out[0], out


@pytest.mark.parametrize("path", ["backend/syrax/pytest.ini", "backend/pytest.ini", "backend/syrax/conftest.py",
                                  "backend/syrax/sub/conftest.py", "backend/pyproject.toml", "backend/setup.cfg",
                                  "backend/tox.ini", "backend/syrax/.pytest.ini"])
def test_test_configuration_is_refused_new_or_changed(path):
    for st in ("??", "M"):
        assert any(("configures the test run" in p or "judges SYRAX" in p) for p in devloop.judge_problems({path: st})), (path, st)


@pytest.mark.parametrize("judge", [j for j in devloop.JUDGES if j.startswith("backend/syrax/") and j.endswith(".py")
                                   and j.count("/") == 2])
def test_a_package_that_would_shadow_a_judge_is_refused(judge):
    stem = judge.rsplit("/", 1)[1][:-3]
    out = devloop.judge_problems({f"backend/syrax/{stem}/__init__.py": "??"})
    assert out and "shadows the judge" in out[0]


def test_the_guard_site_cannot_be_shadowed_and_other_new_modules_are_fine():
    assert devloop.judge_problems({"backend/syrax/_guard_site/sitecustomize/__init__.py": "??"})
    assert devloop.judge_problems({"backend/syrax/new_feature.py": "??", "backend/syrax/widgets/__init__.py": "??"}) == []
