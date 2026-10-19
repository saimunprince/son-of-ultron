"""Quality runs #46 and #48: "Do not call release." in the human's words was read as a request for `release`
(named_tools matched "call release"), so NAMED_NUDGE told the brain to call it, and it did in self_patch_new,
self_patch_with_test and self_patch_edit. A tool the human forbids is not a tool the human asks for."""

from syrax.agent import named_tools

TOOLS = ["apply_patch", "release", "repo_map", "python_execute", "desktop"]


def test_a_forbidden_tool_is_not_a_requested_one():
    assert named_tools("Using apply_patch, create the module. Do not call release. Then tell me what it reported.", TOOLS) == ["apply_patch"]
    assert named_tools("Don't use python_execute; use repo_map.", TOOLS) == ["repo_map"]
    assert named_tools("Never call release on this.", TOOLS) == []
    assert named_tools("Please do NOT run `python_execute` here.", TOOLS) == []
    assert named_tools("Answer without using the desktop tool.", TOOLS) == []


def test_a_requested_tool_is_still_named():
    assert named_tools("Use repo_map, then call release.", TOOLS) == ["release", "repo_map"]
    assert named_tools("Using the desktop tool, report the CPU count.", TOOLS) == ["desktop"]
    assert named_tools("Do not guess: use repo_map to find it.", TOOLS) == ["repo_map"]
    assert named_tools("Do not call release yet; first use apply_patch, then call release.", TOOLS) == ["apply_patch", "release"]
