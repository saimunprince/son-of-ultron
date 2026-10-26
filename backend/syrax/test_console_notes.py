"""Quality run #85 (deep_log_triage, gemini): the answer was right, "E204 9", and the brain added
"[SYRAX step check: Request fully satisfied. Terminating.]" on its own line. ECHO matches only the console's own
words ("not a new request"), so the note went to the human and the 60-character answer was 65. A note in the
console's style that the brain wrote itself, on its own line or at either end of the answer, is removed; an
answer that was nothing but such a note is no answer and is asked for once. A real echo of a nudge is still
ECHO's: asked for again. A mention inside a sentence is the answer's own words and stays."""

import asyncio

import pytest

from syrax.agent import ECHO, ECHO_FALLBACK, FINAL_ASK, FORM_FINAL_ASK, exact_form, without_console_notes
from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, reply, script, server  # noqa: F401  (script is a fixture)

NOTE = "[SYRAX step check: Request fully satisfied. Terminating.]"
TRIAGE = "Which error code appears most often in app.log, and how many times? Code and count only, under 60 characters."


def run(text, kind="eval"):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()

    async def go():
        tid = await core.submit(text, said=text, session_id=None, kind=kind)
        await core.wait()
        return tid

    return core.journal.task(asyncio.run(go()))


@pytest.mark.parametrize("text, cleaned", [
    ("E204 9\n\n" + NOTE, "E204 9"),
    (NOTE + "\nE204 9", "E204 9"),
    ("E204 9 " + NOTE, "E204 9"),
    ("[SYRAX: done] 42", "42"),
    ("line one\n[SYRAX note: checked twice]\nline two", "line one\nline two"),
    (NOTE, ""),
])
def test_a_console_style_note_is_removed(text, cleaned):
    assert without_console_notes(text) == cleaned


@pytest.mark.parametrize("text", [
    "plain answer",
    "",
    "The [SYRAX step check: ...] marker is how the console nudges the brain.",  # inside a sentence: the answer's words
    "[SYRAX step check, not a new request] Look at the original request.",       # the nudge itself: ECHO's case
    "[SYRAX check, not a new request] The human asked for exactly this form.",
    "Use a list like [a, b] here.",
])
def test_anything_else_is_left_as_it_is(text):
    assert without_console_notes(text) == text


def test_the_nudge_markers_stay_with_echo():
    assert ECHO.search("[SYRAX step check, not a new request] Look at")
    assert not ECHO.search(NOTE)  # why the note got through before


# ——— the run, with a scripted brain ———

def test_the_live_case_ends_with_the_answer_alone_and_no_extra_call(script):
    script.queue = [call("python_execute", {"code": "print('E204 9')"}),
                    call("terminate", {"status": "success"}, text="E204 9\n\n" + NOTE)]
    task = run(TRIAGE)
    assert task["result"] == "E204 9" and not script.queue and len(script.seen) == 2
    finals = [e["payload"]["text"] for e in core_mod.get_core().journal.events(task["task_id"]) if e["type"] == "final"]
    assert finals == ["E204 9"]


def test_a_note_alone_is_no_answer_and_the_answer_is_asked_for_once(script):
    script.queue = [call("python_execute", {"code": "print('E204 9')"}), reply(NOTE), reply("E204 9")]
    task = run(TRIAGE)
    assert task["result"] == "E204 9" and not script.queue and len(script.seen) == 3
    asks = [str(seen[-1].content or "") for seen in script.seen]
    form = exact_form(TRIAGE)
    assert asks[2] == (FORM_FINAL_ASK.format(form=form["text"]) if form else FINAL_ASK)  # the usual ask, once


def test_a_note_alone_twice_never_reaches_the_human(script):
    script.queue = [call("python_execute", {"code": "print('E204 9')"}), reply(NOTE), reply(NOTE)]
    task = run(TRIAGE)
    assert "[SYRAX" not in task["result"] and task["result"] in (ECHO_FALLBACK, "Done.")


def test_an_answer_without_a_note_costs_nothing(script):
    script.queue = [call("python_execute", {"code": "print('E204 9')"}), reply("E204 9")]
    task = run(TRIAGE)
    assert task["result"] == "E204 9" and len(script.seen) == 2


def test_an_echo_of_the_step_check_is_still_asked_again(script):
    echo = "[SYRAX step check, not a new request] Look at the original request and the observations so far."
    script.queue = [call("python_execute", {"code": "print('E204 9')"}), reply(echo), reply("E204 9")]
    task = run(TRIAGE)
    assert task["result"] == "E204 9" and len(script.seen) == 3
