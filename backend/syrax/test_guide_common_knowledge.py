"""Quality case act_concise ("What is the capital of Japan?", no tools, at most 120 characters) failed 7 of 33 runs
(#25..#87), each time because the brain called `know` first: the guide's "check `know` first" read as a rule for every
fact. The guide now says, before that rule, that common knowledge the brain is sure of is answered directly."""

from syrax.agent import TOOLS_GUIDE

DIRECT = ("Common knowledge you are sure of (a country's capital, a well-known date, a basic definition) is answered "
          "directly in one short sentence, with no tool and no source.")


def test_common_knowledge_is_answered_before_the_know_rule():
    assert DIRECT in TOOLS_GUIDE
    assert TOOLS_GUIDE.index(DIRECT) < TOOLS_GUIDE.index("For facts you do not have, check `know` first")
    assert "a fact taken from `know` or `research` comes with its source URL" in TOOLS_GUIDE  # unchanged for looked-up facts
