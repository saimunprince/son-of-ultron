"""Live 2026-10-15 (objective 249): an existing test pinned the behaviour the
objective asked to change (`r["gpu"] is None`). SYRAX edited the test, was
refused (existing tests are the contract), reverted it, and ended without
saying what blocked it. When the failing covering test is an existing one the
task did not touch, the refusal says so and asks for that report."""

import asyncio

import pytest

from syrax.test_devloop import git
from syrax.test_release_preflight import PLAN, own, repo

SYRAX = ("backend", "syrax")


def test_an_existing_test_that_pins_the_old_behaviour_is_named_as_the_contract(tmp_path):
    root = repo(tmp_path)
    (root.joinpath(*SYRAX) / "test_mod.py").write_text("import sys; sys.path.insert(0, '.')\nfrom syrax.mod import VALUE\n\ndef test_v():\n    assert VALUE == 1\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "contract")
    j, dl = own(tmp_path, root)
    (root.joinpath(*SYRAX) / "mod.py").write_text("VALUE = 2\n")
    with pytest.raises(ValueError) as e:
        asyncio.run(dl.release("bump VALUE", PLAN))
    assert "The failing test is an existing one (backend/syrax/test_mod.py): it is the contract" in str(e.value)


def test_a_failing_new_test_is_not_called_the_contract(tmp_path):
    root = repo(tmp_path)
    j, dl = own(tmp_path, root)
    (root.joinpath(*SYRAX) / "mod.py").write_text("VALUE = 2\n")
    (root.joinpath(*SYRAX) / "test_mod.py").write_text("import sys; sys.path.insert(0, '.')\nfrom syrax.mod import VALUE\n\ndef test_v():\n    assert VALUE == 3\n")
    with pytest.raises(ValueError) as e:
        asyncio.run(dl.release("bump VALUE", PLAN))
    assert "the tests that cover your change fail" in str(e.value) and "contract" not in str(e.value)
