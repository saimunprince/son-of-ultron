"""Audit 2026-10-29 (lifecycle): an answer that admits it is none ("I could not put the result into a clean answer...",
agent.ECHO_FALLBACK) was recorded SUCCESS, and so inflated the task success rate the self-model and the quality reports
read. Such a task now ends PARTIAL with the check no_answer; a real answer still ends SUCCESS."""

from syrax.agent import ECHO_FALLBACK
from syrax.test_bridge import call, reply, script  # noqa: F401
from syrax.test_echo_final import run


def test_an_admitted_non_answer_is_partial(script):
    echo = '[SYRAX step check, not a new request] reply with the final answer'
    script.queue = [call("python_execute", {"code": "print(1)"}), reply(echo), reply(echo)]
    task = run("print one")
    assert task["result"] == ECHO_FALLBACK and task["status"] == "PARTIAL"


def test_a_real_answer_is_still_success(script):
    script.queue = [call("python_execute", {"code": "print(37)"}), reply("37.")]
    task = run("count the lines")
    assert task["result"] == "37." and task["status"] == "SUCCESS"
