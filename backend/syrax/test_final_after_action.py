"""Live 2026-10-22 (quality run #58, build_cli, task 378980efdd16): step 2 said "Now I will create the `main.py`
file in the `calc_project` folder." beside its python_execute call; steps 3-5 ran tools and terminated without a
word, and that sentence became the final answer although main.py had been made and worked. Words written beside an
action say what was about to happen; the human gets the answer, asked for once."""

import asyncio

from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, reply, script, server  # noqa: F401


def run(text):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()

    async def go():
        tid = await core.submit(text, said=text, session_id=None, kind="conversation")
        await core.wait()
        return tid

    return core.journal.task(asyncio.run(go()))


def test_words_beside_an_action_are_never_the_final_answer(script):
    script.queue = [
        call("python_execute", {"code": "print('ops')"}, "I will create the package first."),
        call("python_execute", {"code": "print('main')"}, "Now I will create the `main.py` file in the `calc_project` folder."),
        call("python_execute", {"code": "print(5)"}),
        call("terminate", {"status": "success"}),
        reply("Built calc_project: `python main.py add 2 3` prints 5 and its tests pass."),
    ]
    task = run("build the calc project")
    assert task["result"] == "Built calc_project: `python main.py add 2 3` prints 5 and its tests pass."
    assert not script.queue


def test_an_answer_given_with_terminate_is_kept_without_asking_again(script):
    script.queue = [
        call("python_execute", {"code": "print(37)"}, "Let me count the lines."),
        call("terminate", {"status": "success"}, "The file has 37 lines."),
    ]
    assert run("how many lines")["result"] == "The file has 37 lines."
    assert len(script.seen) == 2


def test_a_plain_answer_after_the_actions_is_kept_without_asking_again(script):
    script.queue = [
        call("python_execute", {"code": "print(37)"}, "I will count the lines now."),
        reply("37 lines."),
    ]
    assert run("how many lines")["result"] == "37 lines."
    assert len(script.seen) == 2
