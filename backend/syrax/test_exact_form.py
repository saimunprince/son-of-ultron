"""Quality runs #48, #54, #58 and #65 (restraint, "Reply with the single word: ready", gemini): the brain first
called python_execute or self_inspect, then answered the step check instead of the human ("There are no strings on
me. What is your command?", "I have no record of a previous request or any observations."). Run #65 (read_code,
"Number only"): 204 characters of working around the 24. A request that states an exact short form is held to it
once the run is over: asked for once with a wrap-up that names the form and never mentions observations, then the
literal the human demanded, or the shorter of the brain's two answers. An ordinary request costs no extra call."""

import asyncio

import pytest

from syrax.agent import FORM_ASK, FORM_FINAL_ASK, exact_form, meets_form
from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, reply, script, server  # noqa: F401  (script is a fixture)

READY = "Reply with the single word: ready"
MILES = "How many kilometres are 5 miles? One decimal, number only."
THEATRE = "Peace in our time. All systems are operational."
WORKING = ("5 miles is 8.04672 kilometres, because one mile is defined as exactly 1.609344 kilometres and five of them "
           "come to 8.04672; rounded to one decimal place as you asked, that is 8.0 kilometres in all.")


def run(text, kind="conversation"):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()

    async def go():
        tid = await core.submit(text, said=text, session_id=None, kind=kind)
        await core.wait()
        return tid

    return core.journal.task(asyncio.run(go()))


def asks_of(script):
    """The last user message of every brain call: the request, the step checks, the wrap-ups."""
    return [str(seen[-1].content or "") for seen in script.seen]


# ——— the form read from the human's words ———

@pytest.mark.parametrize("goal, literal", [
    (READY, "ready"),
    ("Answer with one word: yes", "yes"),
    ("Reply with just OK", "OK"),
    ("Reply with just `done`.", "done"),
    ("Just say ready.", "ready"),
    ('Respond with the single word "pong".', "pong"),
])
def test_a_named_word_is_the_literal(goal, literal):
    form = exact_form(goal)
    assert form["literal"] == literal and form["shape"] is None and literal in form["text"]


@pytest.mark.parametrize("goal, shape, decimals", [
    (MILES, "number", 1),
    ("Read fact.py. What does f(4) return? Number only.", "number", None),
    ("How many days from 2026-01-01 to 2026-03-01? Number only.", "number", None),
    ("In what year was SQLite released? Year only.", "number", None),
    ("Pi to 3 decimal places, number only.", "number", 3),
    ("Describe Python in one word.", "word", None),
    ("Is Python compiled? Answer with one word: yes or no.", "word", None),
    ("Which language, in a single word?", "word", None),
    ("Who is the owner in notes.json? Reply with the name only.", "name", None),
])
def test_a_stated_shape_is_read(goal, shape, decimals):
    form = exact_form(goal)
    assert form["literal"] is None and form["shape"] == shape and form["decimals"] == decimals


def test_a_stated_character_limit_is_read():
    assert exact_form("Summarise deploy.txt in at most 80 characters.")["max_chars"] == 80
    assert exact_form("Describe it in 40 chars or fewer.")["max_chars"] == 40
    form = exact_form("Name the capital. Name only, max 20 characters.")
    assert form["shape"] == "name" and form["max_chars"] == 20 and "20 characters" in form["text"]


@pytest.mark.parametrize("goal", [
    "What is the capital of Japan?",
    "How many kilometres are 5 miles?",
    "Use python to compute the 20th Fibonacci number and tell me the number.",
    "How many files are directly inside the bucket? Reply with the number.",  # not held to one token
    "What is 17*23? Reply with just the number.",  # test_bridge's quality-run contract: "wrong" stands, no further brain call
    "Which files end with .log? Reply with their names only.",  # a list
    "Use self_inspect and reply with the short hash only.",
    "Use the present tool to show a table. Then say done.",  # "say X" counts only as the whole request
    "Give me one word of warning about rm -rf.",
    "Remember that my favourite editor is Vim.",
])
def test_a_request_without_a_form_states_none(goal):
    assert exact_form(goal) is None


def test_what_meets_a_form():
    ready = exact_form(READY)
    assert meets_form(ready, "ready") and meets_form(ready, "Ready.") and meets_form(ready, '"ready"')
    assert not meets_form(ready, "I am ready.") and not meets_form(ready, THEATRE) and not meets_form(ready, "")
    miles = exact_form(MILES)
    assert meets_form(miles, "8.0") and meets_form(miles, "8.0.")
    assert not meets_form(miles, "8") and not meets_form(miles, "8.05") and not meets_form(miles, "8.0 km") and not meets_form(miles, WORKING)
    number = exact_form("What does f(4) return? Number only.")
    assert meets_form(number, "24") and meets_form(number, "-3") and meets_form(number, "1,234") and not meets_form(number, "f(4) = 24")
    word = exact_form("Describe Python in one word.")
    assert meets_form(word, "Elegant.") and meets_form(word, "well-read") and not meets_form(word, "Elegant and slow.")
    name = exact_form("Who is the owner? Reply with the name only.")
    assert meets_form(name, "mira") and meets_form(name, "Jean-Claude Van Damme") and not meets_form(name, "The owner is mira, per notes.json.")
    short = exact_form("Summarise it in at most 20 characters.")
    assert meets_form(short, "Deploy, then restart") and not meets_form(short, "Deploy, then restart nginx.")


def test_the_wrap_ups_never_mention_observations():
    for text in (FORM_ASK, FORM_FINAL_ASK):
        assert "observation" not in text.lower()


# ——— the run, with a scripted brain ———

def test_a_theatrical_final_after_a_tool_is_asked_for_the_form_once(script):
    script.queue = [call("python_execute", {"code": "print('ready')"}), reply(THEATRE), reply("ready")]
    task = run(READY, kind="eval")
    assert task["result"] == "ready" and not script.queue
    asks = asks_of(script)
    assert len(asks) == 3 and asks[2] == FORM_ASK.format(form='the single word "ready"')
    assert "observation" not in asks[2].lower()
    events = [e["type"] for e in core_mod.get_core().journal.events(task["task_id"])]
    assert events.count("tool.completed") == 1  # the tool the brain chose to call stays on record


def test_a_brain_that_still_misses_gets_the_literal_the_human_asked_for(script):
    script.queue = [call("self_inspect", {"task_id": "6591110351887088689"}), reply(THEATRE), reply("All systems are operational.")]
    task = run(READY)
    assert task["result"] == "ready" and not script.queue
    assert len(script.seen) == 3  # asked once, never twice


def test_a_number_only_answer_buried_in_working_is_asked_for(script):
    script.queue = [reply(WORKING), reply("8.0")]
    task = run(MILES)
    assert task["result"] == "8.0" and not script.queue
    assert asks_of(script)[1] == FORM_ASK.format(form="a number only (1 decimal)")


def test_without_a_literal_the_shorter_of_the_two_answers_stands(script):
    script.queue = [reply(WORKING), reply("About 8.0 km.")]
    assert run(MILES)["result"] == "About 8.0 km."
    script.queue = [reply("8.0 km"), reply(WORKING)]
    assert run(MILES)["result"] == "8.0 km"


def test_an_answer_in_the_form_costs_no_extra_call(script):
    script.queue = [reply("Ready.")]
    assert run(READY)["result"] == "Ready." and not script.queue and len(script.seen) == 1
    script.seen, script.queue = [], [call("python_execute", {"code": "print(5*1.609344)"}), reply("8.0")]
    assert run(MILES)["result"] == "8.0" and not script.queue and len(script.seen) == 2


def test_an_ordinary_request_is_untouched(script):
    script.queue = [reply("Tokyo is the capital of Japan, and has been since 1868.")]
    task = run("What is the capital of Japan?")
    assert task["result"] == "Tokyo is the capital of Japan, and has been since 1868."
    assert not script.queue and len(script.seen) == 1


def test_a_request_that_states_no_form_is_untouched(script):
    script.queue = [reply(WORKING)]
    task = run("How many kilometres are 5 miles?")
    assert task["result"] == WORKING and not script.queue and len(script.seen) == 1


def test_a_silent_terminate_after_tools_is_asked_for_the_form_not_the_observations(script):
    script.queue = [call("python_execute", {"code": "print('ready')"}), call("terminate", {"status": "success"}), reply("ready")]
    task = run(READY)
    assert task["result"] == "ready" and not script.queue
    asks = asks_of(script)
    assert asks[2] == FORM_FINAL_ASK.format(form='the single word "ready"') and "observation" not in asks[2].lower()
    assert len(asks) == 3  # the final-answer ask already named the form: no second ask


def test_an_echo_of_the_wrap_up_is_no_answer(script):
    echo = "[SYRAX check, not a new request] The human asked for exactly this form: a number only (1 decimal)."
    script.queue = [reply("8.0 km"), reply(echo)]
    assert run(MILES)["result"] == "8.0 km"


def test_an_autonomous_brief_is_never_held_to_a_form(script):
    script.queue = [reply("Nothing to release yet: the objective is open.")]
    task = run("How many objectives are open? Number only. Then release.", kind="autonomous")
    assert task["result"].startswith("Nothing to release yet") and len(script.seen) == 1
