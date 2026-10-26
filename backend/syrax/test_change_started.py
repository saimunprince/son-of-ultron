"""Phase 4, "know before changing": the first repository edit of an autonomous task that must release is journaled
change.started (files, covering tests, components, rollback point) and its observation names the covering tests
once. Evidence (journal 2026-09-26..10-26): 13 autonomous releases across 5 tasks were refused because the tests
covering the change failed; one task called `release` 6 times in 10 minutes instead of running the test itself.
Conversations, evals and edits outside the repository get neither the event nor the note."""

import asyncio
import json
import subprocess

import pytest

from syrax import editor
from syrax.agent import CHANGE_NOTE, change_facts, repo_files
from syrax.autonomy import RELEASE_MARK
from syrax.core import _journal_type
from syrax.journal import Event, get_journal
from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, reply, script, server  # noqa: F401

NOTE_HEAD = CHANGE_NOTE.split("{")[0].strip()  # "This change is covered by:"


def git(tree, *args):
    return subprocess.run(["git", *args], cwd=str(tree), capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A task tree (the worktree of an isolated task): a module, its own test, an untested module, the system map."""
    t = tmp_path / "tree"
    (t / "backend" / "syrax").mkdir(parents=True)
    (t / "docs").mkdir()
    (t / "backend" / "syrax" / "widget.py").write_bytes(b"SIZE = 1\nCOLOR = 'red'\n")
    (t / "backend" / "syrax" / "test_widget.py").write_bytes(b"from syrax.widget import SIZE\n\n\ndef test_size():\n    assert SIZE == 1\n")
    (t / "backend" / "syrax" / "lonely.py").write_bytes(b"X = 1\n")
    smap = {"components": [{"component": "widgets", "code": ["backend/syrax/widget.py"], "tests": []}]}
    (t / "docs" / "system_map.json").write_bytes(json.dumps(smap).encode("utf-8"))
    git(t, "init", "-q")
    git(t, "add", "-A")
    git(t, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base")
    monkeypatch.setattr(editor, "ROOT_MAP", (editor.REPO_ROOT, t))
    return t


def run_task(core, text, kind="autonomous"):
    async def go():
        tid = await core.submit(text, said="the objective", session_id=None, kind=kind)
        await core.wait()
        return tid
    return asyncio.run(go())


def started(task_id):
    return [e["payload"] for e in get_journal().events(task_id) if e["type"] == "change.started"]


def tool_texts(script):
    return [m.content or "" for m in script.seen[-1] if getattr(m, "role", None) == "tool"]


def edit(path, old, new):
    return call("str_replace_editor", {"command": "str_replace", "path": str(path), "old_str": old, "new_str": new})


def test_the_first_repository_edit_of_a_release_task_is_journaled_and_names_its_tests_once(script, tree, tmp_path):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    outside = tmp_path / "scratch.txt"
    widget = tree / "backend" / "syrax" / "widget.py"
    head = git(tree, "rev-parse", "--short", "HEAD")
    script.queue = [
        call("str_replace_editor", {"command": "create", "path": str(outside), "file_text": "notes\n"}),  # not the repository
        edit(widget, "SIZE = 1", "SIZE = 2"),
        edit(widget, "COLOR = 'red'", "COLOR = 'blue'"),
        reply("The change is made."),
        reply("I stop here."),  # the answer to the one release nudge
    ]
    tid = run_task(core, f"Change the widget. The objective {RELEASE_MARK}.")
    assert script.queue == []
    assert started(tid) == [{
        "event": "started", "tool": "str_replace_editor", "files": ["backend/syrax/widget.py"],
        "covering_tests": ["backend/syrax/test_widget.py"], "components": ["widgets"], "rollback_point": head, "step": 2,
    }]
    texts = tool_texts(script)
    noted = [t for t in texts if NOTE_HEAD in t]
    assert len(noted) == 1 and len(texts) == 3
    assert noted[0] is texts[1]  # the repository edit, not the scratch file before it, not the edit after it
    assert "This change is covered by: syrax/test_widget.py. Run them with python_execute (python -m pytest syrax/test_widget.py -q" in noted[0]
    assert "before `release`; release runs them too and refuses when they fail." in noted[0]


def test_conversations_and_briefs_without_the_mark_get_no_event_and_no_note(script, tree):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()
    widget = tree / "backend" / "syrax" / "widget.py"
    script.queue = [edit(widget, "SIZE = 1", "SIZE = 2"), reply("Done.")]
    tid = run_task(core, f"Change the widget. The objective {RELEASE_MARK}.", kind="conversation")
    assert script.queue == [] and started(tid) == [] and not any(NOTE_HEAD in t for t in tool_texts(script))
    script.queue = [edit(widget, "SIZE = 2", "SIZE = 3"), reply("Done.")]
    tid = run_task(core, "Change the widget and report.")  # autonomous, but no release asked for
    assert script.queue == [] and started(tid) == [] and not any(NOTE_HEAD in t for t in tool_texts(script))


def test_repo_files_takes_the_patch_paths_and_the_edited_path_inside_the_tree_only(tree, tmp_path):
    diff = "--- a/backend/syrax/widget.py\n+++ b/backend/syrax/widget.py\n@@ -1 +1 @@\n-SIZE = 1\n+SIZE = 2\n"
    assert repo_files("apply_patch", {"diff": diff}) == ["backend/syrax/widget.py"]
    path = str(tree / "backend" / "syrax" / "lonely.py")
    assert repo_files("str_replace_editor", {"command": "insert", "path": path}) == ["backend/syrax/lonely.py"]
    assert repo_files("str_replace_editor", {"command": "view", "path": path}) == []
    assert repo_files("str_replace_editor", {"command": "create", "path": str(tmp_path / "x.txt")}) == []
    (tree / "backend" / "workspace").mkdir()
    assert repo_files("str_replace_editor", {"command": "create", "path": str(tree / "backend" / "workspace" / "y.py")}) == []
    assert repo_files("python_execute", {"code": "open('a','w')"}) == []


def test_change_facts_without_covering_tests_says_none(tree):
    facts = change_facts(["backend/syrax/lonely.py"])
    assert facts["covering_tests"] == [] and facts["components"] == []
    assert facts["rollback_point"] == git(tree, "rev-parse", "--short", "HEAD")
    assert facts["backend"] == str(tree / "backend")


def test_change_started_is_journaled_and_grouped_on_the_wire():
    assert _journal_type({"type": "change", "event": "started", "files": []}) == "change.started"
    assert _journal_type({"type": "change", "event": "other"}) is None
    wire = Event(id=1, ts=0.0, task_id="t", type="change.started", seq=1, payload={"files": ["a.py"]}).wire()
    assert wire["type"] == "change" and wire["event"] == "started" and wire["files"] == ["a.py"]
