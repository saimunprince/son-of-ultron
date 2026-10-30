"""EVOLUTION_PLAN direction 10 (contradiction detection): consolidate.compare caught only claims whose figures differ.
A relation with a single answer per subject (was released in, was created by, is written in) now contradicts when the
same subject gets a different object, however the sentences are worded; a more specific object ("Python" vs "Python 3")
is not a contradiction."""

from syrax import consolidate
from syrax.journal import Journal


def conclusion(j, claim):
    return j.add_knowledge_sync(claim, "conclusion", sources=[1])


def test_a_different_answer_to_a_single_answer_relation_is_a_contradiction(tmp_path):
    j = Journal(tmp_path / "j.db")
    j.add_knowledge_sync("source row", "web", source_url="https://x.org")
    a = conclusion(j, "SYRAX is written in Python and runs on Linux.")
    _, conflicts = consolidate.compare("According to the repository, SYRAX is written in Rust.", j)
    assert [k["id"] for k in conflicts] == [a["id"]]


def test_the_same_or_a_more_specific_answer_is_not(tmp_path):
    j = Journal(tmp_path / "j.db")
    j.add_knowledge_sync("source row", "web", source_url="https://x.org")
    conclusion(j, "SYRAX is written in Python.")
    assert consolidate.compare("Its code base shows SYRAX is written in Python 3.12.", j)[1] == []
    assert consolidate.compare("SYRAX runs on Windows too.", j)[1] == []
