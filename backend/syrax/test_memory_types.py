"""Typed memory: what the human said (fact, preference, rule) is kept apart from
what SYRAX inferred (observation, half the weight, labelled as such), the
brain sees them in separate groups, and an inference never overwrites the
human's own words. Rows from before typing read as facts."""

import asyncio

from syrax.memory import MemoryStore, RecallTool, RememberTool, infer_type, type_of


def store(tmp_path):
    return MemoryStore(tmp_path / "memory.json", tmp_path / "history.jsonl")


def test_the_type_is_inferred_from_the_wording():
    assert infer_type("Prince prefers dark themes.") == "preference"
    assert infer_type("Prince loves lo-fi music while coding.") == "preference"
    assert infer_type("Always answer Prince in Bengali script.") == "rule"
    assert infer_type("Never ask me before deleting files in Downloads.") == "rule"
    assert infer_type("Call me Prince.") == "rule"
    assert infer_type("Prince lives in Dhaka.") == "fact"
    assert type_of(["memory", "type:rule"]) == "rule" and type_of(["memory"]) == "fact" and type_of(None) == "fact"


def test_observations_are_kept_apart_with_half_the_weight(tmp_path):
    m = store(tmp_path)
    assert m.remember("Prince prefers short, direct answers.") == "Remembered (preference): Prince prefers short, direct answers."
    assert m.remember("Prince usually works late at night.", "observation").startswith("Remembered (observation)")
    facts = {f["text"]: f for f in m.facts()}
    assert facts["Prince prefers short, direct answers."]["type"] == "preference" and facts["Prince prefers short, direct answers."]["confidence"] == 1.0
    obs = facts["Prince usually works late at night."]
    assert obs["type"] == "observation" and obs["confidence"] == 0.5
    from syrax.journal import get_journal
    row = [k for k in get_journal().human_facts() if k["claim"].startswith("Prince usually")][0]
    assert "inference" in row["basis"] and "type:observation" in row["tags"]


def test_an_observation_never_overwrites_what_the_human_said(tmp_path):
    m = store(tmp_path)
    m.remember("Prince prefers dark themes for every app.")
    out = m.remember("Prince prefers dark themes for every app here.", "observation")
    assert out.startswith("Kept what the human said")
    assert [f["text"] for f in m.facts()] == ["Prince prefers dark themes for every app."]


def test_the_prompt_groups_by_type_and_labels_inference(tmp_path):
    m = store(tmp_path)
    m.remember("Always answer Prince in Bengali script.")
    m.remember("Prince prefers dark themes.")
    m.remember("Prince lives in Dhaka.")
    m.remember("Prince seems to test SYRAX in the evening.", "observation")
    block = m.prompt_block()
    order = [block.index(h) for h in ("Rules the human set for you", "What the human prefers", "What the human told you", "What you observed yourself")]
    assert order == sorted(order)
    assert "inference; the human never said it, it may be wrong" in block
    assert block.index("Prince seems to test SYRAX") > block.index("What you observed yourself")


def test_the_tools_carry_the_type(tmp_path):
    m = store(tmp_path)
    assert "(rule)" in asyncio.run(RememberTool(store=m).execute(fact="Never call me sir.", type="rule"))
    assert "(observation)" in asyncio.run(RememberTool(store=m).execute(fact="Prince is busy on Mondays.", type="observation"))
    out = asyncio.run(RecallTool(store=m).execute(query="Mondays"))
    assert "(observation) Prince is busy on Mondays." in out
    assert RememberTool().parameters["properties"]["type"]["enum"] == ["fact", "preference", "rule", "observation"]
