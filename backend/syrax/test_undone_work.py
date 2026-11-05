"""Quality run #24 (find_fact): "The launch code is in notes_tuesday.txt. I will retrieve the content of this file to
confirm the code." ended the task with no tool call, and the file was never read. Such a reply is sent back once
(UNDONE_ASK) so the work is done with tools; a plain answer ends the task as before."""

from syrax.agent import UNDONE, UNDONE_ASK
from syrax.test_bridge import call, reply, script  # noqa: F401  (script is a fixture)
from syrax.test_claim_partial import run


def test_the_words_of_undone_work():
    for text in ("The code is in notes.txt. I will retrieve the content of this file to confirm the code.",
                 "I'll now read the file.", "I will check the logs next.", "I will run the tests to verify."):
        assert UNDONE.search(text), text
    for text in ("The code is 7341.", "I will be happy to help.", "Will it run? Yes.", "I read the file: 7341."):
        assert not UNDONE.search(text), text


def test_announced_work_is_done_before_the_task_ends(script):
    script.queue = [
        call("python_execute", {"code": "print('found notes_tuesday.txt')"}),
        reply("The code is in notes_tuesday.txt. I will retrieve the content of this file to confirm the code."),
        call("python_execute", {"code": "print('launch code 7341')"}),
        reply("The launch code is 7341."),
    ]
    task, _ = run("What is the launch code in the meeting notes?")
    assert task["result"] == "The launch code is 7341." and not script.queue
    assert "called no tool" in UNDONE_ASK


def test_a_second_announcement_ends_the_task_honestly(script):
    script.queue = [
        call("python_execute", {"code": "print('x')"}),
        reply("I will read the file now."),
        reply("I will read the file now."),
        reply("The file could not be read."),  # the wrap-up's answer
    ]
    task, _ = run("Read the notes.")
    assert task["result"] != "I will read the file now."


def test_a_page_is_read_as_rendered():
    from syrax.agent import TOOLS_GUIDE

    assert "as the browser renders it" in TOOLS_GUIDE
