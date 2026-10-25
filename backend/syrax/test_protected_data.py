"""Live 2026-10-25 (audit): editor.resolve_path accepted any absolute path, so the
editor, apply_patch and a python_execute path literal could overwrite the files that
hold SYRAX's keys and evidence (brains.json, ws.token, journal.db*), and `forget` was
an ordinary WRITE that SYRAX's own work could turn on the human's memories. The gate
refuses the key/evidence files for every task kind, the owner's settings for autonomous
and eval work, and forget outside a conversation; an ordinary file is unaffected."""

import pytest

from syrax import permissions as P

CONFIG_DIR = P.REPO_ROOT / "backend" / "config"
BRAINS = CONFIG_DIR / "brains.json"
TOKEN = CONFIG_DIR / "ws.token"
CONFIG = CONFIG_DIR / "config.toml"
NORMAL = P.REPO_ROOT / "backend" / "syrax" / "x.py"


def editor(path, cmd="str_replace"):
    return P.classify("str_replace_editor", {"command": cmd, "path": str(path), "old_str": "a", "new_str": "b", "file_text": "x"})


@pytest.mark.parametrize("kind", P.KINDS)
@pytest.mark.parametrize("cmd", sorted(P.EDIT_COMMANDS))
def test_an_edit_of_the_brain_keys_is_refused_for_every_kind(kind, cmd):
    v = P.decide(editor(BRAINS, cmd), kind, f"please {cmd} {BRAINS}")
    assert v.action == "refuse" and v.authorized_by is None, v
    assert "backend/config/brains.json" in v.reason and "keys/evidence" in v.reason and "by hand" in v.reason


@pytest.mark.parametrize("target,expected", [
    (str(TOKEN), "backend/config/ws.token"),
    (str(TOKEN).replace("\\", "/"), "backend/config/ws.token"),
    (str(TOKEN).upper(), "backend/config/ws.token"),
    ("backend/config/journal.db-wal", "backend/config/journal.db-wal"),
    ("backend\\config\\journal.db-shm", "backend/config/journal.db-shm"),
    ("./backend/config/brains.tmp", "backend/config/brains.tmp"),
    (str(P.REPO_ROOT / "backend" / "syrax" / ".." / "config" / "journal.db"), "backend/config/journal.db"),
    (str(P.REPO_ROOT / ".syrax" / "worktrees" / "t1" / "backend" / "config" / "brains.json"), "backend/config/brains.json"),
])
def test_every_spelling_of_a_protected_path_is_recognised(target, expected):
    assert P.data_targets([target], P.PROTECTED_DATA) == [expected]


@pytest.mark.parametrize("target", [str(NORMAL), "backend/config/brains.json.bak", "C:/elsewhere/backend/config/brains.json", "", "*.tmp"])
def test_other_paths_are_not(target):
    assert P.data_targets([target], P.PROTECTED_DATA) == [] and P.data_targets([target], P.OWNER_DATA) == []


@pytest.mark.parametrize("kind", P.KINDS)
def test_python_code_that_writes_the_token_is_refused(kind):
    d = P.classify("python_execute", {"code": f'open(r"{TOKEN}", "w").write("new token")'})
    assert d.level == P.WRITE and str(TOKEN) in d.targets
    v = P.decide(d, kind, "rotate the websocket token")
    assert v.action == "refuse" and "ws.token" in v.reason and "keys/evidence" in v.reason


@pytest.mark.parametrize("kind", P.KINDS)
def test_a_patch_of_the_brain_keys_is_refused(kind):
    diff = "--- a/backend/config/brains.json\n+++ b/backend/config/brains.json\n@@ -1 +1 @@\n-{}\n+{\"order\": []}\n"
    v = P.decide(P.classify("apply_patch", {"diff": diff}), kind, "fix the brains file")
    assert v.action == "refuse" and "brains.json" in v.reason


def test_reading_a_protected_file_is_not_a_write():
    for kind in P.KINDS:
        assert P.decide(editor(BRAINS, "view"), kind, "").action == "allow"
        assert P.decide(P.classify("python_execute", {"code": f'print(open(r"{BRAINS}").read()[:10])'}), kind, "").action == "allow"


def test_the_owners_settings_are_the_humans_to_change_in_conversation_only():
    assert P.decide(editor(CONFIG), "conversation", "").action == "allow"
    for kind in ("autonomous", "eval"):
        v = P.decide(editor(CONFIG), kind, "tune the model settings")
        assert v.action == "refuse" and "backend/config/config.toml" in v.reason and "owner" in v.reason, v
    for name in ("memory.json", "mcp.json"):
        assert P.decide(editor(CONFIG_DIR / name), "autonomous", "").action == "refuse"
        assert P.decide(editor(CONFIG_DIR / name), "conversation", "").action == "allow"


def test_an_ordinary_repository_file_is_unaffected():
    for kind in P.KINDS:
        v = P.decide(editor(NORMAL), kind, "")
        assert (v.action, v.authorized_by) == ("allow", "policy")


def test_forget_is_the_humans_alone():
    d = P.classify("forget", {"query": "dark themes"})
    assert d.level == P.WRITE  # the level is unchanged; the policy is
    assert P.decide(d, "conversation", "forget that I like dark themes").action == "allow"
    assert P.decide(d, "conversation", "").action == "allow"  # today's behaviour in conversation, named or not
    for kind in ("autonomous", "eval"):
        v = P.decide(d, kind, "tidy up the memory, forget the stale facts")
        assert v.action == "refuse" and "human's word" in v.reason, v
    assert P.decide(P.classify("remember", {"text": "x"}), "autonomous", "").action == "allow"  # remembering stays
