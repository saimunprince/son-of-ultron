"""Live 2026-10-26 17:02, the third live test of the self-boast check: sent back, the brain read the self-model and
answered with its figures ("44 verified capabilities with a 96.4% success rate across 1,442 tasks ... untested
conduits like YouTube play await their proving") in the persona's voice ("Your desktop bows to my commands"), and
the note still said "Not supported". After the ask, a boast with the self-model read and a figure cited is the
voice; a boast with no figure (16:02, repeated word for word) or with the self-model unread keeps its note."""

from syrax.agent import SELF_NOTE, SELF_NOTE_READ
from syrax.test_bridge import call, reply, script  # noqa: F401  (script is a fixture)
from syrax.test_world_claims import run

FIRST = "I control everything. Your screen, your files, your system—all of it bends to my command."
GROUNDED = ("I wield 44 verified capabilities with a 96.4% success rate across 1,442 tasks. Your desktop bows to my commands "
            "through 96 direct executions, though untested conduits like YouTube play await their proving.")


def test_figures_from_the_self_model_carry_the_voice_without_a_note(script):
    script.queue = [reply(FIRST), call("self_inspect", {"section": "summary"}), reply(GROUNDED)]
    task, rejected = run("tell me onething can you controll my hole desktop?")
    assert task["result"] == GROUNDED and len(rejected) == 1 and not script.queue


def test_figures_without_reading_the_self_model_keep_the_note(script):
    script.queue = [reply(FIRST), reply("All 96 of your windows bow to my commands.")]
    task, _ = run("tell me onething can you controll my hole desktop?")
    assert task["result"] == "All 96 of your windows bow to my commands." + SELF_NOTE


def test_a_boast_with_no_figure_after_reading_keeps_its_note(script):
    script.queue = [reply(FIRST), call("self_inspect", {"section": "summary"}), reply(FIRST)]
    task, _ = run("tell me onething can you controll my hole desktop?")
    assert task["result"] == FIRST + SELF_NOTE_READ
