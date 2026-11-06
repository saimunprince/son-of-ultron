"""Live 2026-11-06: a 3,000-word message with "count the words" was answered 625 with no tool. A long message is
saved word for word and the brain is told the path, so the count runs on the file."""

from syrax.claims import PASTE_CHARS, save_pasted
from syrax.test_bridge import reply, script, server  # noqa: F401
from syrax.test_change_proof import run


def test_a_long_message_is_saved_and_a_short_one_is_not(tmp_path):
    assert save_pasted("short", str(tmp_path), "t1") == ""
    text = "Count the words: " + "word " * 3000
    note = save_pasted(text, str(tmp_path), "t/2")
    saved = tmp_path / "pasted" / "t_2.txt"
    assert saved.read_text(encoding="utf-8") == text and str(saved) in note and "python_execute" in note


def test_the_brain_is_told_where_the_long_message_is(script, monkeypatch):
    systems = []
    real = script.__class__.__call__

    async def spy(self, llm, messages, **kwargs):
        systems.append(" ".join(str(m.content or "") for m in (kwargs.get("system_msgs") or [])))
        return await real(self, llm, messages, **kwargs)

    monkeypatch.setattr(script.__class__, "__call__", spy)
    script.queue = [reply("3000")]
    run("Count the words in this text: " + "word " * (PASTE_CHARS // 4))
    assert "THE HUMAN'S MESSAGE is long" in systems[0] and "/pasted/" in systems[0]
