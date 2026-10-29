"""Audit 2026-10-28: a symlink in the workspace pointing at backend/config/brains.json (or a judge) passed every
permission check, which judged the link's own name; the editor's open() then followed it into the keys. Every
protected-target check now also judges the path the link really leads to."""

import os

import pytest

from syrax import permissions as P
from syrax.journal import BACKEND_ROOT

KEYS = BACKEND_ROOT / "config" / "brains.json"
JUDGE = BACKEND_ROOT / "syrax" / "guard.py"


@pytest.fixture
def links(tmp_path):
    k, j = tmp_path / "notes.txt", tmp_path / "helper.py"
    try:
        k.symlink_to(KEYS)
        j.symlink_to(JUDGE)
    except OSError as e:  # Windows without Developer Mode may not make symlinks (Windows gate, 2026-10-29)
        pytest.skip(f"this system cannot make symlinks: {e}")
    return k, j


def edit(path):
    return P.classify("str_replace_editor", {"command": "create", "path": str(path), "file_text": "x"})


@pytest.mark.parametrize("kind", ["conversation", "autonomous", "eval"])
def test_a_link_to_the_keys_is_refused_in_every_task_kind(links, kind):
    v = P.decide(edit(links[0]), kind, "write my notes")
    assert v.action == "refuse" and "brains.json" in v.reason


@pytest.mark.parametrize("kind", ["autonomous", "eval"])
def test_a_link_to_a_judge_is_refused_for_own_work(links, kind):
    v = P.decide(edit(links[1]), kind, "")
    assert v.action == "refuse" and "guard.py" in v.reason


def test_the_real_path_is_added_only_when_it_differs(tmp_path, links):
    plain = tmp_path / "plain.txt"
    assert P.with_real([str(plain)]) == [str(plain)]
    forms = P.with_real([str(links[0])])
    assert forms[0] == str(links[0]) and os.path.realpath(forms[1]) == os.path.realpath(KEYS)
