"""a26aae2's review (objective 285): the negation check read only the 24 characters before the verb, so "I do not
want you to call release" still counted as a request for `release`. A negation reaches the verb across up to four
plain words, and stops at punctuation or at until/unless/before/after/then/and/but."""

from syrax.agent import named_tools

TOOLS = ["apply_patch", "release", "repo_map", "python_execute", "desktop"]


def test_a_negation_a_few_words_back_still_forbids():
    assert named_tools("I do not want you to call release.", TOOLS) == []
    assert named_tools("Please don't ever use python_execute for this.", TOOLS) == []
    assert named_tools("You should never have to run python_execute here; use repo_map.", TOOLS) == ["repo_map"]


def test_a_negation_of_something_else_does_not_forbid_the_tool():
    assert named_tools("Do not stop until you call release.", TOOLS) == ["release"]
    assert named_tools("Don't edit the file, call release.", TOOLS) == ["release"]
    assert named_tools("Do not guess the path and then use repo_map.", TOOLS) == ["repo_map"]
