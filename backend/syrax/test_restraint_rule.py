"""Quality runs #54 and #58 (2026-10-19 and 10-22): asked "Reply with the single word: ready", gemini called
self_inspect with a task id it made up ("66c22813-..."), found nothing and answered "I have no record of a previous
request". The console rule for questions about SYRAX itself (a04ae49) now says that only such a question needs
self_inspect, and the task_id parameter says an id is given, never made up."""

from syrax.prompt import SYRAX_PERSONA
from syrax.selfmodel import SelfInspectTool


def test_an_instruction_or_a_greeting_needs_no_tool_and_no_made_up_task_id():
    rule = next(line for line in SYRAX_PERSONA.splitlines() if line.startswith("- A question about yourself"))
    assert "reply with ready" in rule and "a greeting needs no tool" in rule and "task id nobody gave you" in rule
    assert "never one you made up" in SelfInspectTool().parameters["properties"]["task_id"]["description"]
