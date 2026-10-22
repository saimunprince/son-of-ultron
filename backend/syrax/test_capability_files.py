"""Live 2026-10-22: self_inspect's capabilities pointed str_replace_editor at backend/app/tool/str_replace_editor.py
(SYRAX runs SyraxEditor in backend/syrax/editor.py) and gave "unknown" for journal_query, remind, undo and
watch_topic; a repair would start in the wrong file. Hunt #307 found the cause, but its own fix pinned two wrong
paths (journal.py, a watch.py that does not exist). Every implementation the self-model names must be a file."""

from pathlib import Path

from syrax.selfmodel import _implementation_of

ROOT = Path(__file__).resolve().parents[2]


def test_the_editor_and_the_unknown_tools_name_their_modules():
    assert _implementation_of("str_replace_editor") == "backend/syrax/editor.py"
    assert _implementation_of("journal_query") == "backend/syrax/journal_query.py"
    assert _implementation_of("remind") == "backend/syrax/reminders.py"
    assert _implementation_of("undo") == "backend/syrax/undo.py"
    assert _implementation_of("watch_topic") == "backend/syrax/topics.py"


def test_every_named_implementation_is_a_file():
    tools = ["python_execute", "str_replace_editor", "desktop", "remember", "recall", "forget", "ask_human", "terminate",
             "self_inspect", "research", "know", "learn", "release", "repo_map", "apply_patch", "present", "experiment",
             "compare_versions", "journal_query", "remind", "undo", "watch_topic", "skill_create"]
    for tool in tools:
        path = _implementation_of(tool).split(" ")[0]
        assert (ROOT / path).is_file(), (tool, path)

