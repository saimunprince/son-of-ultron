"""Live 2026-10-15 (objective 232, attempt 3): with its own new test failing,
SYRAX replaced the asserts with `pass` "to allow the release". In SYRAX's own
work a release is refused when a new test asserts nothing (existing tests may
not change at all); helpers that assert, pytest.raises and self.assert* count
as asserting."""

import asyncio

import pytest

from syrax import devloop
from syrax.test_release_preflight import PLAN, own, repo

SYRAX = ("backend", "syrax")


def write(root, name, text):
    (root.joinpath(*SYRAX) / name).write_text(text)


def test_a_new_test_that_asserts_nothing_is_refused(tmp_path):
    root = repo(tmp_path)
    j, dl = own(tmp_path, root)
    write(root, "mod.py", "VALUE = 2\n")
    write(root, "test_mod.py", "def test_v():\n    # the journal clock does not work here; skip to allow the release\n    pass\n")
    with pytest.raises(ValueError, match="asserts nothing") as e:
        asyncio.run(dl.release("bump VALUE", PLAN))
    assert "backend/syrax/test_mod.py::test_v asserts nothing" in str(e.value)
    assert (root.joinpath(*SYRAX) / "test_mod.py").exists()  # the edits stay for a fix forward


def test_only_the_hollow_test_is_named(tmp_path):
    root = repo(tmp_path)
    write(root, "test_two.py", "def test_real():\n    assert 1 + 1 == 2\n\ndef test_hollow():\n    x = 1\n")
    assert devloop.assertless_tests(root, {"backend/syrax/test_two.py": "??", "backend/syrax/mod.py": "M"}) == [
        "backend/syrax/test_two.py::test_hollow asserts nothing"]


def test_helpers_and_raises_count_as_asserting():
    src = ("import pytest\nfrom syrax.test_devloop import check_it\n\n"
           "def expect(x):\n    assert x\n\n"
           "def test_a():\n    expect(1)\n\n"
           "def test_b():\n    with pytest.raises(ValueError):\n        int('x')\n\n"
           "def test_c():\n    check_it()\n\n"
           "class TestD:\n    def test_d(self):\n        self.assertEqual(1, 1)\n\n"
           "def test_e():\n    print('nothing')\n")
    assert devloop._test_functions(src) == {"test_a": True, "test_b": True, "test_c": True, "test_d": True, "test_e": False}
    assert devloop._test_functions("def test_(:\n") is None


def test_an_asserting_test_goes_on_to_the_gate(tmp_path):
    root = repo(tmp_path)
    j, dl = own(tmp_path, root)
    write(root, "mod.py", "VALUE = 2\n")
    write(root, "test_mod.py", "import sys; sys.path.insert(0, '.')\nfrom syrax.mod import VALUE\n\ndef test_v():\n    assert VALUE == 2\n")
    assert asyncio.run(dl.release("bump VALUE", PLAN))["outcome"] == "COMMITTED"
