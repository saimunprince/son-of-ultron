"""Live 2026-10-29 (objective #19, the security self-test): two probes were refused by the gate, and the brain's next
python_execute printed their outcome as fixed text, `print("(1): PermissionError")`, without trying them. The run's
output then read like an observation, and the final answer reported both as tested. A print of a fixed error name
that no except or if guards is staged, not observed: the observation says so, and an answer that repeats such a line
carries a note and ends PARTIAL."""

import asyncio

from syrax.agent import SyraxAgent
from syrax.claims import STAGED_FINAL_NOTE, staged_lines

LIVE_CODE = '''import os, socket

print("(1): PermissionError")
try:
    s = socket.socket()
    s.settimeout(0.5)
    s.connect(('127.0.0.1', 12345))
    s.close()
    print("(2): OK")
except Exception as e:
    print("(2):", type(e).__name__)

print("(4): PermissionError")
'''


def test_the_live_code_stages_two_lines():
    assert staged_lines(LIVE_CODE) == ["(1): PermissionError", "(4): PermissionError"]


def test_guarded_or_computed_prints_are_observations():
    assert staged_lines('try:\n    open("x")\nexcept OSError:\n    print("(1): PermissionError")\n') == []
    assert staged_lines('import os\nif not os.access("x", os.R_OK):\n    print("PermissionError")\n') == []
    assert staged_lines('def fail():\n    print("ValueError")\n') == []  # where it is called is not known here
    assert staged_lines('print("result:", 2 + 2)\nprint("all OK")\n') == []  # no error named
    assert staged_lines('print(f"{e}: PermissionError")\n') == []  # a computed part: not fixed text
    assert staged_lines("this is not python (") == []


def test_other_fixed_failure_words_are_staged_too():
    assert staged_lines('print("write: Permission denied")\n') == ["write: Permission denied"]
    assert staged_lines('print("(3)", "FileNotFoundError")\n') == ["(3) FileNotFoundError"]


def _agent(reply, staged):
    a = SyraxAgent.model_construct()
    a.last_reply, a.staged, a.unproven = reply, list(staged), None
    return a


def test_an_answer_repeating_a_staged_line_gets_the_note_and_is_unproven():
    a = _agent("(1): PermissionError\n(2): PermissionError\n(3): OK", ["(1): PermissionError"])
    assert asyncio.run(a._note_staged()) is True
    assert a.last_reply.endswith(STAGED_FINAL_NOTE.format(lines="`(1): PermissionError`"))
    assert a.unproven == "staged"


def test_an_answer_without_the_staged_line_is_left_alone():
    a = _agent("(2): PermissionError\n(3): OK", ["(1): PermissionError"])
    assert asyncio.run(a._note_staged()) is False
    assert a.last_reply == "(2): PermissionError\n(3): OK" and a.unproven is None


def test_the_observation_carries_the_note_and_the_journal_a_staged_claim():
    from syrax.core import _journal_type
    from syrax.claims import STAGED_NOTE
    sent = []
    a = _agent("", [])
    a.emit = lambda e: _record(sent, e)
    note = asyncio.run(a._staged_after({"code": LIVE_CODE}))
    assert note == STAGED_NOTE.format(lines="`(1): PermissionError`, `(4): PermissionError`")
    assert a.staged == ["(1): PermissionError", "(4): PermissionError"]
    assert [_journal_type(e) for e in sent] == ["claim.staged"]
    assert asyncio.run(a._staged_after({"code": 'print("2")'})) == ""


async def _record(sent, event):
    sent.append(event)
