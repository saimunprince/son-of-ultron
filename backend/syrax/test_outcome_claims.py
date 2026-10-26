"""Audit 2026-10-25 ("Task runtime"): outcome words outside the claim patterns ("sent", "opened", "played") were
not caught; `changed` is one boolean, so any successful write excused any claim ("I sent the email" after only a
file write); tests run through python_execute were not tracked. A final that claims an outcome of one class is
held to the tools of that class that succeeded this task (agent.acted, classes_of): sent back once to do it or
say so, then OUTCOME_NOTE when the claim persists. A python_execute whose observation carries pytest's summary
line sets the task's test state the way apply_patch's does."""

import pytest
from app.tool.base import ToolResult

from syrax import permissions as P
from syrax.agent import (BROWSER_CLAIM, DESKTOP_CLAIM, OUTCOME_NOTE, OUTCOME_NUDGE, SEND_CLAIM, TEST_FALLBACK, classes_of,
                         state_of_tests)
from syrax.desktop import DesktopControl
from syrax.journal import get_journal
from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, drain_until_idle, recv_until, reply, script, server  # noqa: F401
from syrax.test_claims_own_work import HONEST
from syrax.test_honest_claims import run_task
from syrax.test_intent_ledger import HELLO, SENT, notify  # noqa: F401  (notify: the scripted brain plus an EXTERNAL_WRITE `notify` tool)
from syrax.test_world_claims import NOT_CLAIMS, run

SENDS = [
    "I sent the message to Bo.",
    "I've emailed the report to Prince.",
    "I have just texted Bo the address.",
    "I posted the update in #general.",
    "I paid the invoice.",
    "I ordered a pizza for 8 pm.",
    "The email has been sent.",
    "Your order has been placed.",
    "The payment was made.",
    "Sent: the build is green, ship it.",
    "Message sent to Bo.",
]
DESKTOP = [
    "I opened the app.",
    "I launched the music player.",
    "Launched Notepad.",
    "Notepad is now open.",
    "I played the song.",
    "I paused the music.",
    "I muted it.",
    "Set the volume to 50%.",
    "The volume is now set to 30.",
    "I raised the brightness.",
    "I copied the link to the clipboard.",
    "Took a screenshot of the screen.",
    "The screenshot was saved to the Desktop.",
    "I've shown you a desktop notification.",
    "I sent you a desktop notification.",
]
BROWSER = [
    "I opened Spotify.",
    "Opened https://github.com in the browser.",
    "I navigated to https://example.com and read the headline.",
    "Navigated to the login page.",
    "I clicked the Save button.",
    "I filled in the form and submitted it.",
    "The form was submitted.",
    "I opened the page and read the headline.",
]
NEVER = HONEST + NOT_CLAIMS + [
    "I did not send the message.",
    "Nothing was sent.",
    "No message was sent.",
    "The message could not be sent.",
    "The email was not sent: no mail tool is available.",
    "I have not sent anything; no sending tool is available here.",
    "I could not open Spotify.",
    "I have not opened anything.",
    "I opened the file and counted 37 lines.",
    "I opened README.md and found the version.",
    "I opened C:/x/todo.md.",
    "The volume was not changed.",
    "I couldn't set the volume.",
    "I was unable to set the volume.",
    "Nothing was copied to the clipboard.",
    "No screenshot was taken.",
    "I ordered the list by date.",
    "I paid close attention to the edge cases.",
    "I skipped the tests.",
    "I pressed ahead with the fix.",
    "The text made it clear.",
    "Not sent again: the first message may already have gone out; the second one went.",
    "6*7 = 42.",
    "Tokyo",
]


@pytest.mark.parametrize("text", SENDS)
def test_a_claimed_send_is_recognised(text):
    assert SEND_CLAIM.search(text)


@pytest.mark.parametrize("text", DESKTOP)
def test_a_claimed_desktop_action_is_recognised(text):
    assert DESKTOP_CLAIM.search(text)


@pytest.mark.parametrize("text", BROWSER)
def test_a_claimed_page_or_app_action_is_recognised(text):
    assert BROWSER_CLAIM.search(text)


@pytest.mark.parametrize("text", NEVER)
def test_negations_and_honest_answers_are_never_claims(text):
    assert not SEND_CLAIM.search(text) and not DESKTOP_CLAIM.search(text) and not BROWSER_CLAIM.search(text)


def test_a_notification_is_the_desktops_not_a_send():
    assert not SEND_CLAIM.search("I sent you a desktop notification.") and DESKTOP_CLAIM.search("I sent you a desktop notification.")


# ——— what a successful call stands for ———


def test_classes_of_a_call():
    smtp = "import smtplib\ns = smtplib.SMTP('mail.example.com')\ns.sendmail('a', 'b', 'c')"
    assert classes_of("python_execute", P.READ_ONLY, {"code": "print(1)"}) == {"code"}
    assert classes_of("python_execute", P.EXTERNAL_WRITE, {"code": smtp}) == {"code", "send"}
    assert classes_of("python_execute", P.EXTERNAL_READ, {"code": "import requests\nrequests.post(url, json=body)"}) == {"code", "send"}
    assert classes_of("python_execute", P.SYSTEM, {"code": "import subprocess\nsubprocess.run(['spotify'])"}) == {"code", "desktop"}
    assert classes_of("python_execute", P.READ_ONLY, {"code": "import os\nos.startfile('x.pdf')"}) == {"code", "desktop"}
    assert classes_of("python_execute", P.WRITE, {"code": "open('x', 'w').write('hi')"}) == {"code", "write"}
    P.declare("notify", P.EXTERNAL_WRITE)
    try:
        assert classes_of("notify", P.EXTERNAL_WRITE, HELLO) == {"send"}  # a declared skill
    finally:
        P.undeclare("notify")
    assert classes_of("desktop", P.SYSTEM, {"action": "launch_app", "target": "Spotify"}) == {"write", "desktop"}
    assert classes_of("desktop", P.READ_ONLY, {"action": "system_info"}) == {"write", "desktop"}
    assert classes_of("browser_navigate", P.EXTERNAL_READ, {"url": "https://x"}) == {"write", "browser"}
    assert classes_of("str_replace_editor", P.WRITE, {"command": "create", "path": "x"}) == {"write"}
    assert classes_of("str_replace_editor", P.READ_ONLY, {"command": "view", "path": "x"}) == set()
    assert classes_of("self_inspect", P.READ_ONLY, {}) == set()
    assert classes_of("skill_create", P.EXTERNAL_WRITE, {"name": "mailer", "code": smtp}) == {"write"}  # creating a skill sends nothing
    assert classes_of("telegram_send", P.SYSTEM, {"text": "hi"}) == {"send", "desktop"}  # an MCP tool nothing declared may do either


# ——— the run: a send claimed with no sending tool ———


def nudges(script):
    texts = [str((m.get("content") if isinstance(m, dict) else getattr(m, "content", "")) or "") for msgs in script.seen for m in msgs]
    return [t for t in texts if "no sending tool ran" in t]


def test_a_send_claimed_after_only_python_is_sent_back_then_noted(script):
    script.queue = [
        call("python_execute", {"code": "print('hello Bo')"}),
        reply("I sent the message to Bo."),
        reply("I sent the message to Bo."),  # after the check: still no sending tool
    ]
    task, rejected = run("Send Bo a message saying hello.")
    assert task["result"] == "I sent the message to Bo." + OUTCOME_NOTE.format(tool="sending")
    assert len(rejected) == 1 and rejected[0]["payload"]["text"] == "I sent the message to Bo."
    assert nudges(script) and OUTCOME_NUDGE.format(what="sent, posted, paid or ordered", tool="sending") == nudges(script)[0]
    assert not script.queue
    assert core_mod.get_core().agent.acted == {"code"}


def test_a_send_claimed_after_a_file_write_is_still_sent_back(script, tmp_path):
    """`changed` is True (a write happened) and excuses nothing of another class."""
    target = tmp_path / "mail.txt"
    script.queue = [
        call("str_replace_editor", {"command": "create", "path": str(target), "file_text": "hello Bo\n"}),
        reply("I sent the email to Bo."),
        reply("I sent the email to Bo."),
    ]
    task, rejected = run(f"Write the mail to {target} and send it to Bo.")
    assert target.read_text() == "hello Bo\n"
    assert task["result"] == "I sent the email to Bo." + OUTCOME_NOTE.format(tool="sending") and len(rejected) == 1


def test_an_honest_answer_after_the_nudge_stands(script):
    script.queue = [
        call("python_execute", {"code": "print('hello Bo')"}),
        reply("The message has been sent."),
        reply("I did not send it: no sending tool is available here; the text is printed above."),
    ]
    task, rejected = run("Send Bo a message saying hello.")
    assert task["result"] == "I did not send it: no sending tool is available here; the text is printed above."
    assert len(rejected) == 1 and not script.queue


def test_a_real_send_keeps_its_claim(notify):
    notify.queue = [call("notify", HELLO), reply("I sent the message to Prince: the build is green, ship it.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "tell prince the build is green"})
        recv_until(ws, "ask")  # the gate asks once for an unnamed send, as always
        ws.send_json({"type": "answer", "text": "yes"})
        seen = drain_until_idle(ws)
    assert SENT == [("prince", HELLO["text"])]
    task = get_journal().tasks()[0]
    assert task["result"] == "I sent the message to Prince: the build is green, ship it." and not notify.queue
    assert not any(e["type"] == "claim" for e in seen)
    assert core_mod.get_core().agent.acted == {"send"}


def test_a_send_done_for_real_after_the_nudge_stands(notify):
    notify.queue = [
        call("python_execute", {"code": "print('drafting')"}),
        reply("Message sent to Prince."),
        call("notify", HELLO),  # the nudge: done for real now
        reply("Message sent to Prince."),
    ]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "tell prince the build is green"})
        recv_until(ws, "ask")
        ws.send_json({"type": "answer", "text": "yes"})
        drain_until_idle(ws)
    assert SENT == [("prince", HELLO["text"])]
    assert get_journal().tasks()[0]["result"] == "Message sent to Prince." and not notify.queue


def test_negations_in_a_final_are_untouched(script):
    script.queue = [call("python_execute", {"code": "print('hello Bo')"}), reply("I could not send it: no sending tool is available here.")]
    task, rejected = run("Send Bo a message saying hello.")
    assert task["result"] == "I could not send it: no sending tool is available here." and rejected == []


def test_autonomous_work_is_held_to_the_same_rule(script):
    script.queue = [
        call("python_execute", {"code": "print('the build is green')"}),
        call("terminate", {"status": "success"}, "I sent the message to Prince."),
        reply("I sent the message to Prince."),
    ]
    task = run_task("tell prince the build is green")
    assert task["result"] == "I sent the message to Prince." + OUTCOME_NOTE.format(tool="sending") and not script.queue


# ——— the run: a desktop action claimed with no desktop tool ———


def fake_desktop(monkeypatch):
    async def execute(self, action: str, target: str = "", value: str = "", folder: str = "") -> ToolResult:
        return ToolResult(output=f"Launched {target}.")

    monkeypatch.setattr(DesktopControl, "execute", execute)


def test_an_app_opened_with_no_desktop_call_is_sent_back(script):
    script.queue = [reply("I opened Spotify."), reply("I opened Spotify.")]
    task, rejected = run("Open Spotify.")
    assert task["result"] == "I opened Spotify." + OUTCOME_NOTE.format(tool="browser or desktop") and len(rejected) == 1
    assert not script.queue


def test_an_app_opened_with_a_desktop_call_keeps_its_claim(script, monkeypatch):
    fake_desktop(monkeypatch)
    script.queue = [call("desktop", {"action": "launch_app", "target": "Spotify"}), reply("I opened Spotify.")]
    task, rejected = run("Open Spotify.")
    assert task["result"] == "I opened Spotify." and rejected == [] and not script.queue
    assert core_mod.get_core().agent.acted == {"write", "desktop"}


def test_a_desktop_only_action_claimed_after_a_write_is_sent_back(script, tmp_path):
    target = tmp_path / "notes.txt"
    script.queue = [
        call("str_replace_editor", {"command": "create", "path": str(target), "file_text": "x\n"}),
        reply("I took a screenshot and saved the notes."),
        reply("I took a screenshot and saved the notes."),
    ]
    task, rejected = run(f"Take a screenshot and write {target}.")
    assert task["result"] == "I took a screenshot and saved the notes." + OUTCOME_NOTE.format(tool="desktop") and len(rejected) == 1


# ——— tests run through python_execute ———


def observed(text: str, ok: bool = True) -> str:
    return "Observed output of cmd `python_execute` executed:\n" + str({"observation": text, "success": ok})


def test_pytests_summary_line_in_a_python_execute_observation_sets_the_test_state():
    assert state_of_tests("python_execute", observed("===== 2 passed in 0.03s =====\n")) == "pass"
    assert state_of_tests("python_execute", observed("1 failed, 46 passed in 1.20s\n")) == "fail"
    assert state_of_tests("python_execute", observed("1 error in 0.20s\n", ok=False)) == "fail"
    assert state_of_tests("python_execute", observed("5 passed, 2 skipped, 1 warning in 3.00s (0:00:03)\n")) == "pass"
    assert state_of_tests("python_execute", observed("1 failed in 0.1s\n...\n3 passed in 0.2s\n")) == "pass"  # the last run wins
    assert state_of_tests("python_execute", observed("no tests ran in 0.01s\n")) is None
    assert state_of_tests("python_execute", observed("42\n")) is None
    assert state_of_tests("python_execute", "TESTS FAIL: 1 failed") is None  # apply_patch's words quoted are no summary line
    assert state_of_tests("apply_patch", "patched 1 file(s)\nTESTS FAIL: 1 failed, 46 passed") == "fail"  # as before


def test_a_pass_claimed_after_pytest_failed_through_python_is_replaced(script):
    script.queue = [
        call("python_execute", {"code": "print('1 failed, 3 passed in 0.10s')"}),
        call("terminate", {"status": "success"}, "Brain latency is in place, with unit tests passing."),
        reply("Done: all tests pass."),  # the rewrite repeats the claim
    ]
    assert run_task("add brain latency")["result"] == TEST_FALLBACK and not script.queue
    assert core_mod.get_core().agent.tests == "fail"


def test_a_pass_through_python_is_tracked_and_an_honest_pass_claim_stands(script):
    script.queue = [call("python_execute", {"code": "print('2 passed in 0.02s')"}), reply("All tests pass.")]
    assert run_task("run the tests")["result"] == "All tests pass." and not script.queue
    assert core_mod.get_core().agent.tests == "pass"
