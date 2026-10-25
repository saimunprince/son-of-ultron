"""Memory truth (2026-10-25 audit, "Memory, skills, security"): `remember` used to store whatever text the model
passed as a "human said" fact at confidence 1.0, even when the human never said it. Now the tool knows the human's
words for the task: text grounded in them is a fact at 1.0, text the model invented is an observation at 0.5 with
an "inferred" basis and a reply that says so; "remember that ..." from the human stays a fact. An overwrite journals
what it replaced (`previous`) and the new row takes the new type and confidence (a human fact over an observation
is a fact at 1.0, not an observation at 0.5). `forget` refuses a needle that would match everything and a sweep of
more than five rows the human never asked for."""

import asyncio

import pytest

from syrax.journal import get_journal
from syrax.memory import ForgetRefused, ForgetTool, MemoryStore, RecallTool, RememberTool, grounded, names
from syrax.test_bridge import ORIGIN, TestClient, boot, call, drain_until_idle, recv_until, reply, script, server  # noqa: F401

SAID = "I'm Prince, I live in Dhaka and I prefer dark themes in every app."


def store(tmp_path):
    return MemoryStore(tmp_path / "memory.json", tmp_path / "history.jsonl")


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def remember_tool(m, said):
    t = RememberTool(store=m)
    t.said_provider = lambda: said
    return t


def forget_tool(m, said):
    t = ForgetTool(store=m)
    t.said_provider = lambda: said
    return t


def updates():
    return [e["payload"] for e in get_journal().recent_events(200) if e["type"] == "knowledge.updated"]


# ——— remember: the human's words make a fact, the model's own words an observation ———


def test_text_the_human_said_is_a_fact_at_full_confidence(tmp_path):
    m = store(tmp_path)
    out = run(remember_tool(m, SAID).execute(fact="Prince lives in Dhaka."))
    assert out == "Remembered (fact): Prince lives in Dhaka."
    f = m.facts()[0]
    assert f["type"] == "fact" and f["confidence"] == 1.0
    row = get_journal().human_facts()[0]
    assert row["basis"] == "human said (remember tool)" and "type:fact" in row["tags"]


def test_model_invented_text_is_an_observation_and_the_reply_says_so(tmp_path):
    m = store(tmp_path)
    out = run(remember_tool(m, "Set up the project folder for me.").execute(fact="Prince prefers dark themes."))
    assert out.startswith("Stored as an observation, not a fact") and "never said" in out and "inferred" in out
    f = m.facts()[0]
    assert f["type"] == "observation" and f["confidence"] <= 0.5
    row = get_journal().human_facts()[0]
    assert "type:observation" in row["tags"] and "type:preference" not in row["tags"]
    assert row["basis"].startswith("SYRAX inferred from the conversation")
    assert "(observation) Prince prefers dark themes." in run(RecallTool(store=m).execute(query="dark themes"))
    # the type the model asked for does not promote it either
    out = run(remember_tool(m, "Set up the project folder for me.").execute(fact="Prince's shell is fish.", type="fact"))
    assert out.startswith("Stored as an observation") and m.facts()[-1]["type"] == "observation"


def test_an_explicit_remember_instruction_stays_a_fact(tmp_path):
    m = store(tmp_path)
    out = run(remember_tool(m, "Remember that my favourite editor is Vim.").execute(fact="Prince's favourite editor is Vim.", type="preference"))
    assert out == "Remembered (preference): Prince's favourite editor is Vim."
    assert m.facts()[0]["confidence"] == 1.0 and m.facts()[0]["type"] == "preference"


def test_grounding_is_a_substring_or_most_content_words(tmp_path):
    assert grounded("I live in Dhaka", SAID)  # a substring of what was said
    assert grounded("Prince lives in Dhaka.", SAID)  # prince, dhaka: 2 of 3 content words
    assert not grounded("Prince prefers dark themes.", "Set up the project folder for me.")
    assert not grounded("Prince works late at night.", SAID)  # 1 of 4
    assert not grounded("anything", "") and not grounded("", SAID)
    m = store(tmp_path)
    # the store itself, with no human words known, takes the text at its word (direct callers vouch for it)
    assert m.remember("Prince prefers dark themes.") == "Remembered (preference): Prince prefers dark themes."


def test_the_agent_gives_the_tools_the_humans_words(script):
    script.queue = [
        call("remember", {"fact": "Prince prefers dark themes."}, "Noting that."),
        reply("Noted."),
        call("remember", {"fact": "Prince prefers dark themes."}, "Noting that."),
        reply("Noted."),
    ]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "what time is it in Dhaka?"})
        res, _ = recv_until(ws, "tool_result")
        assert res["name"] == "remember" and "Stored as an observation, not a fact" in res["output"]  # the bridge prefixes "Observed output"
        drain_until_idle(ws)
        ws.send_json({"type": "task", "text": "Remember that I prefer dark themes."})
        res, _ = recv_until(ws, "tool_result")
        assert "Updated memory" in res["output"] and "was an observation, now a preference at 1.0" in res["output"]
        drain_until_idle(ws)
    rows = get_journal().human_facts()
    assert len(rows) == 1 and rows[0]["confidence"] == 1.0 and "type:preference" in rows[0]["tags"]


# ——— overwrite: the event keeps what was there, the row takes the new type and confidence ———


def test_an_overwrite_journals_what_it_replaced(tmp_path):
    m = store(tmp_path)
    m.remember("Prince's favourite editor is Vim.", "preference")
    assert m.remember("Prince's favourite editor is VS Code.", "preference").startswith("Updated memory")
    ev = updates()[-1]
    assert ev["previous"] == {"claim": "Prince's favourite editor is Vim.", "type": "preference", "confidence": 1.0}
    assert ev["claim"] == "Prince's favourite editor is VS Code." and ev["type"] == "preference" and ev["confidence"] == 1.0


def test_a_human_fact_over_an_observation_becomes_a_fact_at_full_confidence(tmp_path):
    m = store(tmp_path)
    m.remember("Prince's shell is zsh.", "observation")
    assert m.facts()[0]["type"] == "observation" and m.facts()[0]["confidence"] == 0.5
    out = m.remember("Prince's shell is fish.", said="my shell is fish these days")
    assert out.startswith("Updated memory: Prince's shell is zsh. -> Prince's shell is fish.") and "was an observation, now a fact at 1.0" in out
    f = m.facts()[0]
    assert f["text"] == "Prince's shell is fish." and f["type"] == "fact" and f["confidence"] == 1.0
    row = get_journal().human_facts()[0]
    assert row["basis"] == "human said (remember tool)" and "type:fact" in row["tags"] and "type:observation" not in row["tags"]
    ev = updates()[-1]
    assert ev["previous"] == {"claim": "Prince's shell is zsh.", "type": "observation", "confidence": 0.5}
    assert ev["type"] == "fact" and ev["confidence"] == 1.0
    # and the other way round still holds: an inference never overwrites the human's word
    assert m.remember("Prince's shell is bash.", said="unrelated request").startswith("Kept what the human said")
    assert m.facts()[0]["text"] == "Prince's shell is fish."


# ——— forget: no needle that matches everything, no silent sweep ———


def test_forget_with_a_two_char_needle_is_refused(tmp_path):
    m = store(tmp_path)
    m.remember("Prince lives in Dhaka.")
    m.remember("Prince prefers dark themes.")
    out = run(forget_tool(m, "forget a").execute(query="a"))
    assert out.startswith("Refused") and "too short" in out
    with pytest.raises(ForgetRefused):
        m.forget("me")
    assert len(m.facts()) == 2
    # a whole word still works, a fragment of one does not
    assert m.forget("prin") == [] and len(m.facts()) == 2
    assert run(forget_tool(m, "forget dhaka").execute(query="Dhaka")).startswith("Forgot 1 memory matching 'Dhaka':")
    assert [f["text"] for f in m.facts()] == ["Prince prefers dark themes."]


def test_forget_matching_six_rows_is_refused_unless_the_human_named_them(tmp_path):
    m = store(tmp_path)
    for text in ["Prince edits Python in Vim.", "Vim is open on the laptop all day.", "The Vim config lives in dotfiles.",
                 "Prince mapped jj to escape in Vim.", "Vim plugins are managed with lazy.", "Prince learned Vim in 2019."]:
        assert m.remember(text).startswith("Remembered")
    assert len(m.facts()) == 6
    out = run(forget_tool(m, "forget vim").execute(query="vim"))
    assert out.startswith("Refused: 6 memories match 'vim'") and "forget everything about vim" in out
    assert len(m.facts()) == 6
    with pytest.raises(ForgetRefused):
        m.forget("vim", said="")
    assert not names("vim", "forget vim") and names("vim", "forget everything about Vim") and names("vim", "drop all my Vim memories")
    assert names("everything", "forget everything") and not names("everything", "forget everything about Vim")
    out = run(forget_tool(m, "forget everything about Vim").execute(query="vim"))
    assert out.startswith("Forgot 6 memories matching 'vim':") and m.facts() == []
