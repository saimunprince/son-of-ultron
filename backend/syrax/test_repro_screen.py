"""Brief Factory (2026-10-22): repro.screen refuses a test that could not prove a change before anything runs it.
Live failures it answers: objective #283 "fixed" a quality case by pinning a constant the case itself edits, an
own test once asserted nothing (`pass` "to allow the release"), and brief tests with key-shaped strings were
refused by the diff scan four times."""

from syrax import repro
from syrax.test_devloop import git, repo

GOOD = '''"""Live: "Do not call release." was read as a request for release."""

from syrax.agent import named_tools


def test_a_forbidden_tool_is_not_requested():
    assert named_tools("Do not call release.", ["release"]) == []
'''


GOOD_INTENT = GOOD.replace("from syrax.agent import named_tools", "from syrax.intent import args_hash").replace(
    'assert named_tools("Do not call release.", ["release"]) == []', 'assert args_hash({"a": 1}) == args_hash({"a": 1})')


def test_a_test_that_can_prove_the_change_passes_the_screen():
    # agent.py is a judge since 2026-10-29 (test_judge_agent_brains): the passing example targets intent.py
    assert "args_hash" in GOOD_INTENT and "named_tools" not in GOOD_INTENT
    assert repro.screen("backend/syrax/test_named_forbidden.py", GOOD_INTENT, ["backend/syrax/intent.py"]) == []


def test_tests_that_cannot_prove_anything_are_refused():
    cases = {
        "not a test path": ("backend/syrax/named_forbidden.py", GOOD, [], "a repro test is a new file"),
        "asserts nothing": ("backend/syrax/test_a.py", "from syrax.agent import named_tools\n\n\ndef test_x():\n    named_tools('a', [])\n",
                            [], "asserts nothing"),
        "a constant": ("backend/syrax/test_a.py", "from syrax.agent import named_tools\n\n\ndef test_x():\n    assert False\n",
                       [], "asserts only a constant"),
        "no SYRAX code": ("backend/syrax/test_a.py", "def test_x():\n    assert 1 + 1 == 3\n", [], "must import the SYRAX code"),
        "another module": ("backend/syrax/test_a.py", GOOD, ["backend/syrax/editor.py"], "test the code the change is for"),
        "a judge": ("backend/syrax/test_a.py", GOOD, ["backend/syrax/agent.py", "backend/syrax/autonomy.py"], "judges SYRAX's own work"),
        "a test as the fix": ("backend/syrax/test_a.py", GOOD, ["backend/syrax/test_agent.py"], "not tests"),
        "a shell": ("backend/syrax/test_a.py", GOOD + "\n\ndef test_y():\n    import subprocess\n    assert subprocess.run(['git']).returncode == 0\n",
                    [], "(SYSTEM)"),
        "no parse": ("backend/syrax/test_a.py", "def test_x(:\n", [], "does not parse"),
    }
    for name, (rel, text, files, expected) in cases.items():
        problems = repro.screen(rel, text, files)
        assert any(expected in p for p in problems), (name, problems)


def test_a_key_shaped_literal_is_refused_like_the_diff_scan_would():
    key = "gsk" + "_" + "A1b2C3d4E5f6G7h8I9j0K1l2"
    text = GOOD + f'\n\ndef test_z():\n    assert named_tools("{key}", []) == []\n'
    assert any("possible secret" in p for p in repro.screen("backend/syrax/test_a.py", text))


def test_an_existing_test_is_the_contract_and_cannot_be_filed_again(tmp_path):
    root = repo(tmp_path)
    (root / "backend" / "syrax" / "test_old.py").write_text("x = 1\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "old test")
    head = git(root, "rev-parse", "HEAD")
    assert any("already exists" in p for p in repro.screen("backend/syrax/test_old.py", GOOD, [], root, head))
    assert not any("already exists" in p for p in repro.screen("backend/syrax/test_new.py", GOOD, [], root, head))


def test_the_filed_text_and_its_hash_ignore_line_endings():
    assert repro.norm_text("a\r\nb") == "a\nb\n" and repro.test_sha("a\r\nb\n\n") == repro.test_sha(b"a\nb")
