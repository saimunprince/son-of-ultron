"""Live 2026-10-14 (task f0a6e150812b): a final answer began 'The user says:
"[SYRAX step check, not a new request] ...' and reasoned about the nudge
instead of answering. A final that repeats a console nudge is asked for once
more; if it is still an echo, the human never gets the console's own words."""

import asyncio

import pytest

from syrax.agent import ECHO, ECHO_FALLBACK
from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, get_journal, reply, script, server  # noqa: F401


@pytest.mark.parametrize("text", [
    'The user says: "[SYRAX step check, not a new request] Look at the original request..."',
    "[SYRAX check, not a new request] Your answer says something was deleted",
    "Done. [SYRAX step check, not a new request] reply with the final answer",
])
def test_echoes_of_the_console_are_recognised(text):
    assert ECHO.search(text)


def test_a_tool_call_written_as_the_final_answer_is_not_an_answer():
    assert ECHO.search("<tool_call> <function=python_execute> <parameter=code> import os </parameter> </function> </tool_call>")
    assert ECHO.search("<function=str_replace_editor> <parameter=command> view")


@pytest.mark.parametrize("text", ["Tokyo.", "The user says they prefer dark themes; noted.", "Step check passed: 37 lines.",
                                  "Use the function keyword to define it."])
def test_answers_are_not_echoes(text):
    assert not ECHO.search(text)


def run(text):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()

    async def go():
        tid = await core.submit(text, said=text, session_id=None, kind="conversation")
        await core.wait()
        return tid

    return core.journal.task(asyncio.run(go()))


def test_an_echoed_final_is_asked_for_again(script):
    script.queue = [
        call("python_execute", {"code": "print(37)"}),
        reply('The user says: "[SYRAX step check, not a new request] Look at the original request."'),
        reply("37."),
    ]
    assert run("count the lines")["result"] == "37."
    assert not script.queue


def test_a_persistent_echo_never_reaches_the_human(script):
    echo = '[SYRAX step check, not a new request] reply with the final answer'
    script.queue = [call("python_execute", {"code": "print(1)"}), reply(echo), reply(echo)]
    assert run("print one")["result"] == ECHO_FALLBACK
