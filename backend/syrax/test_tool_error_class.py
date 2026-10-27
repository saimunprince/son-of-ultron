"""Phase One, error classification (journal audit 2026-10-27): 628 tool.failed events carried no cause, so failures
could only be grouped by tool. Every new tool.failed event carries ``error_class`` (tool_error.CLASSES); a completed
call carries none. The table below is real outputs from the live journal (2026-10-13..27), trimmed."""

import pytest

from syrax import tool_error
from syrax.tool_error import CLASSES, tool_error_class
from syrax.test_bridge import ORIGIN, TestClient, boot, call, drain_until_idle, get_journal, recv_until, reply, script, server  # noqa: F401

OBS = "Observed output of cmd `{}` executed:\n"

TABLE = [
    # refused: the permission gate, a release that refuses its plan, a held intent
    ("python_execute", "Error: refused: runs shell commands (SYSTEM) is not done in autonomous work; leave it to the human.",
     True, "refused"),
    ("release", OBS.format("release") + "Error: release refused: refused: the tests that cover the change failed",
     True, "refused"),
    ("release", OBS.format("release") + "Error: release refused: nothing to release: the worktree has no change",
     False, "refused"),
    ("send_email", "Error: refused: the same send_email action may already have gone out (step 3): check what happened "
     "first; do not repeat it blindly. This is final: do not retry it; do the rest or report.", False, "refused"),
    # timeout
    ("python_execute", OBS.format("python_execute") + "{'observation': 'Execution timeout after 60 seconds', 'success': False}",
     False, "timeout"),
    ("browser_hang", "Error: browser_hang did not answer within 1 s; the call was abandoned (the page or server may still "
     "be busy): try once more with a simpler step, or report it", False, "timeout"),
    # mismatch
    ("apply_patch", OBS.format("apply_patch") + "Error: apply_patch refused: the patch does not apply cleanly: error: "
     "patch failed: backend/syrax/selfedit.py:1\nerror: backend/syrax/selfedit.py: patch does not apply", False, "mismatch"),
    ("str_replace_editor", OBS.format("str_replace_editor") + "Error: No replacement was performed: old_str did not "
     "appear verbatim in C:\\ai-agent\\son-of-ultron\\backend\\syrax\\journal_query.py.", False, "mismatch"),
    ("str_replace_editor", OBS.format("str_replace_editor") + "Error: No replacement was performed. Multiple occurrences "
     "of old_str `x = 1` in lines [3, 9]. Please ensure it is unique", False, "mismatch"),
    ("apply_patch", OBS.format("apply_patch") + "Error: apply_patch failed: git apply failed after --check passed: error: "
     "backend/syrax/test_brain_ms.py: already exists in working directory", False, "mismatch"),
    # misuse
    ("str_replace_editor", OBS.format("str_replace_editor") + "Error: Parameter `command` is required: view, create, "
     "str_replace, insert or undo_edit.", False, "misuse"),
    ("present", OBS.format("present") + "Error: unknown argument(s) ['sheet_name']; use kind, title, rows", False, "misuse"),
    ("journal_query", OBS.format("journal_query") + "Error: no such column: payload. Schema: archive(id, ts, head)",
     False, "misuse"),
    ("str_replace_editor", OBS.format("str_replace_editor") + "Error: Unrecognized command rename. The allowed commands "
     "for the str_replace_editor tool are: view, create", False, "misuse"),
    ("apply_patch", OBS.format("apply_patch") + "Error: apply_patch refused: ../docs/EXECUTION_PLAN.md: paths must be "
     "repository-relative, inside the repository", False, "misuse"),
    ("learn", OBS.format("learn") + "Error: learn refused: cite at least one knowledge_id or URL", False, "misuse"),
    ("desktop", OBS.format("desktop") + "Error: find_files needs a name pattern in target", False, "misuse"),
    # not_found
    ("python_execute", OBS.format("python_execute") + "{'observation': \"FileNotFoundError: [Errno 2] No such file or "
     "directory: 'C:\\\\ai-agent\\\\son-of-ultron\\\\backend\\\\workspace\\\\stats.py'\", 'success': False}", False, "not_found"),
    ("str_replace_editor", OBS.format("str_replace_editor") + "Error: The path C:\\ai-agent\\son-of-ultron\\backend\\"
     "workspace\\quality\\report\\ethanol.md does not exist.", False, "not_found"),
    ("desktop", OBS.format("desktop") + "Error: No installed app matches 'WhatsApp'. Try the app's full name", False,
     "not_found"),
    ("python_execute", OBS.format("python_execute") + "{'observation': \"ModuleNotFoundError: No module named 'pandas'\", "
     "'success': False}", False, "not_found"),
    # external
    ("web_search", "Error: ConnectionError: HTTPSConnectionPool(host='api.example.com', port=443): Max retries exceeded",
     False, "external"),
    ("research", "Error: HTTP 503 from the search service", False, "external"),
    ("research", "Error: 429 Client Error: Too Many Requests for url: https://api.example.com/q", False, "external"),
    # crash
    ("python_execute", OBS.format("python_execute") + "{'observation': 'OperationalError: attempt to write a readonly "
     "database', 'success': False}", False, "crash"),
    ("python_execute", OBS.format("python_execute") + "{'observation': \"KeyError: 'customer_id'\", 'success': False}",
     False, "crash"),
    ("python_execute", OBS.format("python_execute") + "{'observation': 'SyntaxError: invalid syntax (<string>, line 2)', "
     "'success': False}", False, "crash"),
    ("skill_test", "Traceback (most recent call last):\n  File \"skill.py\", line 3, in run\n    1/0\n", False, "crash"),
    # other
    ("python_execute", OBS.format("python_execute") + "{'observation': '', 'success': False}", False, "other"),
    ("wallpaper", "wallpaper: Windows refused the wallpaper", False, "other"),
]


@pytest.mark.parametrize("name,output,refused,expected", TABLE, ids=[f"{t[3]}-{i}" for i, t in enumerate(TABLE)])
def test_real_failures_get_their_class(name, output, refused, expected):
    assert tool_error_class(name, output, refused) == expected


def test_every_class_is_covered_and_the_answer_is_always_a_class():
    assert {t[3] for t in TABLE} == set(CLASSES)
    for odd in (None, "", 42, {"observation": None}, "Error"):
        assert tool_error_class("x", odd) in CLASSES
    assert [cls for cls, _ in tool_error._RULES] == [c for c in CLASSES if c not in ("refused", "other")]


def test_the_event_flag_wins_and_the_classifier_is_deterministic():
    patch_fail = "Error: apply_patch refused: the patch does not apply cleanly"
    assert tool_error_class("apply_patch", patch_fail, True) == "refused"
    assert {tool_error_class("apply_patch", patch_fail) for _ in range(5)} == {"mismatch"}


def test_a_failed_call_is_journaled_with_its_class_and_a_completed_one_without(script):
    script.queue = [
        call("python_execute", {"code": "open('no_such_file_for_error_class.txt')"}, cid="miss1"),
        call("python_execute", {"code": "print('fine')"}, cid="ok1"),
        reply("done"),
    ]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "read a file"})
        failed, _ = recv_until(ws, "tool_result")
        done, _ = recv_until(ws, "tool_result")
        recv_until(ws, "final")
        drain_until_idle(ws)
    assert failed["ok"] is False and failed["error_class"] == "not_found"
    assert done["ok"] is True and "error_class" not in done
    j = get_journal()
    task = j.tasks()[0]
    steps = [e for e in j.events(task["task_id"]) if e["type"] in ("tool.completed", "tool.failed")]
    assert [e["type"] for e in steps] == ["tool.failed", "tool.completed"]
    assert steps[0]["payload"]["error_class"] == "not_found" and "refused" not in steps[0]["payload"]
    assert "error_class" not in steps[1]["payload"]
