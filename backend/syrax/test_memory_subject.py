from syrax.memory import MemoryStore


def store(tmp_path):
    return MemoryStore(tmp_path / "memory.json", tmp_path / "history.jsonl")


def test_a_new_value_for_the_same_subject_replaces_the_old_one(tmp_path):
    m = store(tmp_path)
    m.remember("Prince's favourite editor is Vim.", "preference")
    out = m.remember("Prince's favourite editor is VS Code.", "preference")
    assert out.startswith("Updated memory")
    assert [f["text"] for f in m.facts()] == ["Prince's favourite editor is VS Code."]


def test_other_subjects_stay_and_an_observation_never_replaces_the_human(tmp_path):
    m = store(tmp_path)
    m.remember("Prince's favourite editor is Vim.", "preference")
    m.remember("Prince's favourite language is Python.", "preference")
    assert m.remember("Prince's favourite editor is Emacs.", "observation").startswith("Kept what the human said")
    assert sorted(f["text"] for f in m.facts()) == ["Prince's favourite editor is Vim.", "Prince's favourite language is Python."]
