"""Audit 2026-10-25, release-policy hole 2: the reviewer saw new files by name
only ("New files: backend/syrax/test_x.py"), so a new test, the very thing an
own change is proven by, was never judged. The review prompt now carries each
new file whole as a /dev/null diff, inside the overall cap, and names the cut
when the diff was too long."""

import asyncio
import re

from syrax import review as R
from syrax.devloop import DevLoop
from syrax.journal import Journal
from syrax.test_devloop import PASS, repo
from syrax.test_review_fallback import GOOD, Msg

PLAN = {"why": "objective evidence", "risk": "callers of mod", "tests": "test_two.py"}
TEST_TWO = "from syrax.mod import VALUE\n\n\ndef test_two():\n    assert VALUE == 2\n"


class Store:
    order = ["gemini", "upstage"]

    def enabled(self, p):
        return True


class Capturing:
    """A router that keeps the review prompt it was asked."""

    store = Store()

    def __init__(self):
        self.prompts = []

    async def _call(self, pid, messages, tools, choice, images=False):
        self.prompts.append(messages[-1]["content"])
        return Msg(GOOD)


def test_the_reviewer_reads_a_new_file_whole_through_a_release(tmp_path):
    root = repo(tmp_path)
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("improve mod", kind="autonomous")
    j.record_sync("brain.answered", {"provider": "gemini"}, task_id=t)
    dl = DevLoop(j, root=root, gates=lambda: PASS, task_id_provider=lambda: t, snapshot_dir=tmp_path / "rb")
    router = Capturing()
    seen = {}

    async def real_review(info, summary, authors):
        seen["info"] = info
        return await R.review(router, info, summary, authors)

    dl.reviewer = real_review
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 2\n")
    (root / "backend" / "syrax" / "test_two.py").write_text(TEST_TWO)
    rep = asyncio.run(dl.release("bump VALUE and prove it", PLAN))
    assert rep["outcome"] == "COMMITTED" and rep["review"]["reviewer"] == "upstage"
    assert seen["info"]["new_files"] == {"backend/syrax/test_two.py": TEST_TWO}  # inspect hands the content over
    prompt = router.prompts[-1]
    assert "-VALUE = 1\n+VALUE = 2" in prompt  # the tracked change, as before
    assert "--- /dev/null\n+++ b/backend/syrax/test_two.py\n@@ -0,0 +1,5 @@\n" in prompt
    assert "+def test_two():\n+    assert VALUE == 2\n" in prompt  # the new file's lines, not its name alone
    assert "New files:" not in prompt and "more lines not shown" not in prompt


def test_a_new_file_diff_looks_like_gits():
    d = R.new_file_diff("docs/a.md", "# a\n\nbody\n")
    assert d == "diff --git a/docs/a.md b/docs/a.md\nnew file mode 100644\n--- /dev/null\n+++ b/docs/a.md\n@@ -0,0 +1,3 @@\n+# a\n+\n+body\n"
    body = R.diff_for_review({"diff": "--- a/x\n+++ b/x\n-1\n+2", "untracked": ["docs/a.md"], "new_files": {"docs/a.md": "# a\n"}})
    assert body == "--- a/x\n+++ b/x\n-1\n+2\ndiff --git a/docs/a.md b/docs/a.md\nnew file mode 100644\n--- /dev/null\n+++ b/docs/a.md\n@@ -0,0 +1,1 @@\n+# a\n"
    unseen = R.diff_for_review({"diff": "d\n", "untracked": ["docs/a.md"]})  # an older caller without the content
    assert "New files (content not provided): docs/a.md" in unseen


def test_a_module_change_with_its_test_fits_and_a_cut_is_named():
    module = "".join(f"-old line {i} of the module, with a comment that makes it realistically long\n+new line {i} of the module, with a comment that makes it realistically long\n" for i in range(80))
    test = "\n".join(f"    assert value({i}) == {i}  # one assertion per line, as a generated table test would have" for i in range(60))
    info = {"diff": "--- a/backend/syrax/mod.py\n+++ b/backend/syrax/mod.py\n" + module, "untracked": ["backend/syrax/test_mod_more.py"],
            "new_files": {"backend/syrax/test_mod_more.py": "def test_more():\n" + test + "\n"}}
    body = R.diff_for_review(info)
    assert len(info["diff"]) > 12000  # did not fit the old cap
    assert "more lines not shown" not in body and body.endswith("+    assert value(59) == 59  # one assertion per line, as a generated table test would have\n")
    huge = {"diff": "", "untracked": ["backend/syrax/big.py"], "new_files": {"backend/syrax/big.py": "\n".join(f"x{i} = {i}" for i in range(4000))}}
    cut = R.diff_for_review(huge)
    assert len(cut) <= R.MAX_DIFF + len(R.TRUNCATED) + 8 and cut.endswith("\n")
    n = int(re.search(r"… (\d+) more lines not shown: reject if you cannot judge it", cut).group(1))
    assert n > 0 and n + len(cut.split("\n" + R.TRUNCATED.format(n=n))[0].splitlines()) == R.new_file_diff("backend/syrax/big.py", huge["new_files"]["backend/syrax/big.py"]).count("\n")
    assert "+x0 = 0\n" in cut and f"+x3999 = 3999" not in cut
