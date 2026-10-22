"""Live 2026-10-22 (hunt #307): SYRAX's fix pointed watch_topic at backend/syrax/watch.py, which does not exist, and
its test pinned the same path; test and fix agreed, so the proof said PROVEN and brief 308 was filed (the human
dropped it before it landed). A proof checks that test and fix agree, not that they are true. What code can check:
a fix names only files that exist at the base or that it creates."""

from syrax import repro
from syrax.test_devloop import git
from syrax.test_repro_hunt import hunt_with_task
from syrax.test_repro_prove import FIX, REPRO, TEST, shaped_repo

NAMES_A_PHANTOM = FIX.replace('+    return a + b', '+    return a + b  # see backend/syrax/watch.py')


def test_a_fix_may_name_only_files_that_exist_or_that_it_creates(tmp_path):
    root = shaped_repo(tmp_path)
    head = git(root, "rev-parse", "HEAD")
    assert repro.phantom_paths(NAMES_A_PHANTOM, root, head) == [
        f"the fix names backend/syrax/watch.py, which does not exist at {head[:7]} and is not created by the fix"]
    assert repro.phantom_paths(FIX.replace("+    return a + b", "+    return a + b  # backend/syrax/calc.py"), root, head) == []
    creates = NAMES_A_PHANTOM + "--- /dev/null\n+++ b/backend/syrax/watch.py\n@@ -0,0 +1 @@\n+X = 1\n"
    assert repro.phantom_paths(creates, root, head) == []


def test_a_hunt_whose_fix_names_a_phantom_file_is_not_filed(tmp_path):
    root, j, o, task = hunt_with_task(tmp_path, "calc.add subtracts.", NAMES_A_PHANTOM + f"\n# untracked: {TEST}\n" + REPRO)
    out = repro.harvest(j, o, task, root)
    assert out["event"] == "repro.rejected" and "backend/syrax/watch.py" in out["reason"]
