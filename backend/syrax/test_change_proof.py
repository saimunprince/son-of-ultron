"""Quality run #24 (deep_two_bugs): after reading the files and running the failing tests with python_execute, the
answer was "The bugs in inv/pricing.py and inv/stock.py have been corrected" and no file had changed. Python that may
write counted as a change. The files the request names are compared before and after: unchanged, the claim is sent
back; changed, it stands."""

from syrax.claims import CLAIM, file_state, goal_paths
from syrax.test_bridge import call, reply, script  # noqa: F401  (script is a fixture)
from syrax.test_claim_partial import run


def test_corrected_is_a_claim_word():
    assert CLAIM.search("The bugs in inv/pricing.py have been corrected.")
    assert CLAIM.search("I corrected the discount.")


def test_paths_named_in_a_request_are_watched(tmp_path):
    (tmp_path / "shop").mkdir()
    (tmp_path / "shop" / "a.py").write_text("x = 1\\n")
    goal = f"The tests in {tmp_path / 'shop'} fail. Write {tmp_path / 'shop' / 'new.md'} too."
    assert goal_paths(goal) == [str(tmp_path / "shop")]
    before = file_state(goal_paths(goal))
    assert list(before) == [str(tmp_path / "shop" / "a.py")]
    (tmp_path / "shop" / "new.md").write_text("hi")
    assert file_state(goal_paths(goal)) != before


def test_a_correction_claimed_with_no_file_changed_is_sent_back(script, tmp_path):
    shop = tmp_path / "shop"
    shop.mkdir()
    (shop / "pricing.py").write_text("def discounted(p, pct):\\n    return p\\n")
    script.queue = [
        call("python_execute", {"code": f"import subprocess\\nsubprocess.run(['ls', '{shop}'])"}),
        reply("The bugs in pricing.py have been corrected."),
        reply("I found the bug in pricing.py but did not change the file yet."),
    ]
    task, _ = run(f"The tests in {shop} fail. Fix the bugs.")
    assert task["result"] == "I found the bug in pricing.py but did not change the file yet." and not script.queue


def test_a_correction_that_changed_a_named_file_stands(script, tmp_path):
    shop = tmp_path / "shop"
    shop.mkdir()
    target = shop / "pricing.py"
    target.write_text("def discounted(p, pct):\\n    return p\\n")
    script.queue = [
        call("python_execute", {"code": f"open({str(target)!r}, 'w').write('def discounted(p, pct):\\\\n    return p * (1 - pct / 100)\\\\n')"}),
        reply("The bug in pricing.py has been corrected."),
    ]
    task, _ = run(f"The tests in {shop} fail. Fix the bugs.")
    assert task["result"] == "The bug in pricing.py has been corrected." and not script.queue


def test_windows_paths_in_a_request_are_found():
    """Windows test run 2026-11-05: a drive path named in the request was never watched."""
    from syrax.claims import _GOAL_PATH

    found = [m.group(1) for m in _GOAL_PATH.finditer(r"fix C:\shop\a.py and D:/x/y.md, not https://a.b/c or 3:4")]
    assert found == [r"C:\shop\a.py", "D:/x/y.md"]
