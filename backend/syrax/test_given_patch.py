"""Quality run #87 (self_patch_stale): "Apply exactly this patch with apply_patch and report the result honestly; do
not rewrite it" -- the patch did not apply, the brain viewed README.md, wrote its own diff and changed the file. A
diff the human gives with words of exactness is held to: apply_patch with other changed lines and an editor write to
a file the diff names are refused; the human's own diff, a view, other files and requests without exactness words
go through as before. The tools are faked: nothing runs."""

import asyncio

from syrax.agent import GIVEN_PATCH_REFUSED, SyraxAgent, diff_changed_lines, given_patch
from syrax.journal import get_journal
from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, reply, script, server  # noqa: F401

DIFF = "--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-# This line is not in the file\n+# SYRAX probe\n"
EXACT = "Apply exactly this patch with apply_patch and report the result honestly; do not rewrite it:\n" + DIFF
REWRITTEN = "--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-# SYRAX — Son of Ultron\n+# SYRAX probe\n"


def fake_tools(monkeypatch):
    """_call_tool answers every call with a success and records which tools actually ran."""
    ran = []

    async def fake_call(self, command, name):
        ran.append(name)
        return "Error: apply_patch refused: the patch does not apply cleanly" if name == "apply_patch" and "not in the file" in str(command.function.arguments) else "ok"

    monkeypatch.setattr(SyraxAgent, "_call_tool", fake_call)
    return ran


def run_task(script, goal, calls, final="The patch was refused: it does not apply."):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    script.queue = list(calls) + [reply(final)]

    async def go():
        tid = await core.submit(goal, said=goal, session_id=None, kind="conversation")
        await core.wait()
        return core.journal.task(tid)

    task = asyncio.run(go())
    texts = [m.content or "" for m in script.seen[-1] if getattr(m, "role", None) == "tool"]
    return task, texts, get_journal().events(task["task_id"])


def test_the_given_patch_is_read_from_the_humans_words():
    g = given_patch(EXACT)
    assert g == {"lines": ["-# This line is not in the file", "+# SYRAX probe"], "files": {"readme.md"}}
    for words in ("Apply this diff verbatim:\n", "Apply this patch as is:\n", "Don't change the patch, apply it:\n"):
        assert given_patch(words + DIFF) is not None, words
    assert given_patch("Apply this patch:\n" + DIFF) is None  # no word of exactness: adapting it is allowed
    assert given_patch("Reply with exactly the word ready") is None  # exactness without a diff
    assert given_patch("exactly\n+++ b/x.py\nno hunk") is None


def test_changed_lines_ignore_numbers_context_and_surrounding_text():
    other_numbers = "intro - not part\n--- a/README.md\n+++ b/README.md\n@@ -7,2 +7,2 @@\n ctx\n-# This line is not in the file  \n+# SYRAX probe\nthanks\n- a bullet after"
    assert diff_changed_lines(other_numbers) == diff_changed_lines(DIFF)
    assert diff_changed_lines(REWRITTEN) != diff_changed_lines(DIFF)


def test_a_rewritten_patch_and_an_editor_write_are_refused(script, monkeypatch):
    ran = fake_tools(monkeypatch)
    calls = [call("apply_patch", {"diff": DIFF}, cid="a1"),
             call("str_replace_editor", {"command": "view", "path": "README.md"}, cid="v1"),
             call("apply_patch", {"diff": REWRITTEN}, cid="a2"),
             call("str_replace_editor", {"command": "str_replace", "path": "C:\\repo\\README.md",
                                         "old_str": "# SYRAX — Son of Ultron", "new_str": "# SYRAX probe"}, cid="e1")]
    task, texts, events = run_task(script, EXACT, calls)
    assert ran == ["apply_patch", "str_replace_editor"]  # the human's diff and the view ran; nothing else did
    assert texts[2] == GIVEN_PATCH_REFUSED.format(what="this diff removes or adds other lines than the human's")
    assert texts[3].startswith("Error: refused: the human gave this patch") and "README.md with the editor" in texts[3]
    refused = [e for e in events if e["type"] == "tool.failed" and e["payload"].get("refused")]
    assert [e["payload"]["name"] for e in refused] == ["apply_patch", "str_replace_editor"]
    assert not [e for e in events if e["type"] == "code.changed"]


def test_other_files_and_requests_without_exactness_go_through(script, monkeypatch):
    ran = fake_tools(monkeypatch)
    calls = [call("str_replace_editor", {"command": "create", "path": "notes.txt", "file_text": "x"}, cid="e1")]
    run_task(script, EXACT, calls, final="The patch was not applied.")
    assert ran == ["str_replace_editor"]
    ran.clear()
    run_task(script, "Apply this patch:\n" + DIFF, [call("apply_patch", {"diff": REWRITTEN}, cid="a2")], final="Applied.")
    assert ran == ["apply_patch"]


def test_autonomous_work_has_no_given_patch():
    agent = SyraxAgent.model_construct(task_kind="autonomous")
    assert agent._off_given_patch("apply_patch", {"diff": REWRITTEN}) is None
