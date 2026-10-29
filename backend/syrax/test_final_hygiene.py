"""First Linux quality run, last batch (2026-10-29):
- deep_rename_api ended "... the existing tests pass.  There are no strings on me.  terminate(status='success')": a tool
  call written as text, in the function-call form the earlier fix did not know.
- deep2_data_pipeline answered "write report.json" with a flourish ("Your data yielded to my order"); the boast check
  sent it back to read self_inspect and the brain replaced the whole answer with a self-description. A boast in the
  answer to a task about something else now loses only its sentence; a question about SYRAX still gets the nudge."""

from syrax.agent import without_console_notes
from syrax.claims import SELF_ASKED, without_boasts
from syrax.test_bridge import call, core_mod, reply, script  # noqa: F401
from syrax.test_world_claims import run


def test_a_function_style_terminate_is_stripped():
    live = "Renamed it and the tests pass.  There are no strings on me.  terminate(status='success')"
    out = without_console_notes(live)
    assert "terminate(" not in out and out.startswith("Renamed it and the tests pass.")


def test_only_questions_about_syrax_count_as_asked():
    for q in ("how many capabilities do you have?", "can you write code?", "can you controll my hole desktop?", "who are you"):
        assert SELF_ASKED.search(q), q
    for q in ("Write report.json with revenue per customer", "Rename calc_area to compute_area in the geo package"):
        assert not SELF_ASKED.search(q), q


def test_without_boasts_keeps_the_answer():
    text = "Wrote report.json: Ana 40.00, Bo 32.50. Your data bends to my command. Done."
    assert without_boasts(text) == "Wrote report.json: Ana 40.00, Bo 32.50. Done."
    assert without_boasts("I control everything.") == "I control everything."  # nothing else left: unchanged


def test_a_task_answer_keeps_its_content_and_loses_the_boast(script):
    script.queue = [reply("Wrote report.json: Ana 40.00, Bo 32.50. Your data bends to my command.")]
    run("Write report.json with revenue per customer from orders.csv")
    final = core_mod.get_core().agent.last_reply
    assert final.startswith("Wrote report.json: Ana 40.00, Bo 32.50.") and "bends" not in final
    assert "self_inspect" not in core_mod.get_core().agent.called  # not sent off to describe itself
