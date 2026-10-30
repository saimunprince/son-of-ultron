"""EVOLUTION_PLAN direction 100 (skill generalization): duplicate_of only refused a new skill that copied a VERIFIED
one. Two skills already kept that serve one subject with the same arguments (live 2026-10-30: youtube_open and
youtube_play, both {query}) stayed two tools. The daily radar now proposes one general skill in their place, once per
pair of versions; the human decides."""

from syrax import skillevo
from syrax.journal import Journal

CODE = '''class Skill:
    parameters = {"type": "object", "properties": {%s}}
'''


def skill(j, root, name, purpose, props):
    d = root / name
    d.mkdir(parents=True)
    (d / "skill.py").write_text(CODE % ", ".join(f'"{p}": {{"type": "string"}}' for p in props))
    j.upsert_skill_sync(name, purpose, str(d), "VERIFIED")


def test_same_family_same_arguments_or_alike_purposes_are_proposed_once(tmp_path):
    j = Journal(tmp_path / "j.db")
    root = tmp_path / "skills"
    skill(j, root, "youtube_open", "Opens the YouTube search results page for the words", ["query"])
    skill(j, root, "youtube_play", "Play something on YouTube: the first video a search finds", ["query"])
    skill(j, root, "youtube_transcript", "The transcript of a YouTube video", ["url", "languages"])
    skill(j, root, "pdf_text", "Read the text of a PDF file page by page", ["path", "page"])
    skill(j, root, "pdf_reader", "Read the text of a PDF file and its pages", ["file"])
    skill(j, root, "weather", "Current weather and forecast for a place", ["query"])
    pairs = {tuple(g["skills"]) for g in skillevo.generalizations(j, root)}
    assert pairs == {("youtube_open", "youtube_play"), ("pdf_reader", "pdf_text")}
    assert skillevo.propose_generalizations(j, root=root) == 2
    assert skillevo.propose_generalizations(j, root=root) == 0  # once per pair of versions
    props = [e["payload"] for e in j.recent_events(100) if e["type"] == "proposal.created"]
    assert all(p["kind"] == "skill_generalization" for p in props)
    yt = next(p for p in props if p["skills"] == ["youtube_open", "youtube_play"])
    assert "query" in yt["proposal"] and "one skill" in yt["proposal"]


def test_disabled_or_missing_code_is_not_proposed(tmp_path):
    j = Journal(tmp_path / "j.db")
    root = tmp_path / "skills"
    skill(j, root, "youtube_open", "Opens YouTube search", ["query"])
    j.upsert_skill_sync("youtube_play", "Play on YouTube", str(root / "youtube_play"), "VERIFIED")  # no code here
    assert skillevo.generalizations(j, root) == []
