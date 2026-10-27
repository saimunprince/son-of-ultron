"""A bare name is no subject: "Prince is X" never overwrites "Prince was Y" (2026-10-27 review)."""

from syrax.memory import MemoryStore


def store(tmp_path):
    return MemoryStore(tmp_path / "memory.json", tmp_path / "history.jsonl")


def test_unrelated_facts_about_the_same_person_all_stay(tmp_path):
    m = store(tmp_path)
    for text in ("Prince is a developer.", "Prince was born in Dhaka.", "Prince is vegetarian."):
        assert m.remember(text).startswith("Remembered"), text
    assert sorted(f["text"] for f in m.facts()) == [
        "Prince is a developer.", "Prince is vegetarian.", "Prince was born in Dhaka."]


def test_the_human_is_x_never_collapses_into_one_row(tmp_path):
    m = store(tmp_path)
    m.remember("The human is a night owl.")
    m.remember("The human is learning Rust.")
    assert len(m.facts()) == 2


def test_an_observation_about_a_bare_name_is_stored_not_dropped(tmp_path):
    m = store(tmp_path)
    m.remember("Prince is a developer.")
    out = m.remember("Prince is probably tired today.", "observation")
    assert not out.startswith("Kept what the human said"), out
    assert len(m.facts()) == 2


def test_a_named_subject_still_replaces_and_identical_text_still_dedupes(tmp_path):
    m = store(tmp_path)
    m.remember("Prince's sister is a doctor.")
    assert m.remember("Prince's sister is a teacher.").startswith("Updated memory: Prince's sister is a doctor.")
    m.remember("Prince is a developer.")
    m.remember("Prince is a developer.")
    assert sorted(f["text"] for f in m.facts()) == ["Prince is a developer.", "Prince's sister is a teacher."]
