import asyncio
import json
import os
import stat

from syrax.memory import ForgetTool, MemoryStore, RecallTool, RememberTool


def store(tmp_path):
    return MemoryStore(tmp_path / "memory.json", tmp_path / "history.jsonl")


def test_remember_recall_forget_roundtrip(tmp_path):
    m = store(tmp_path)
    assert m.remember("Prince prefers dark themes.").startswith("Remembered")
    m.remember("Prince is building SYRAX, son of Ultron.")
    assert [f["text"] for f in m.recall("dark theme")][0] == "Prince prefers dark themes."
    assert m.forget("dark themes") == ["Prince prefers dark themes."]
    assert [f["text"] for f in m.facts()] == ["Prince is building SYRAX, son of Ultron."]
    assert stat.S_IMODE(os.stat(tmp_path / "memory.json").st_mode) == 0o600


def test_near_duplicates_update_instead_of_piling_up(tmp_path):
    m = store(tmp_path)
    m.remember("Prince likes lo-fi music while coding")
    assert "Updated" in m.remember("Prince likes lo-fi music while coding.")
    assert len(m.facts()) == 1


def test_secrets_are_refused(tmp_path):
    m = store(tmp_path)
    for s in ["my password is hunter2", "groq key gsk_abc123", "api key is sk-12345"]:
        assert m.remember(s).startswith("Refused"), s
    assert m.facts() == []


def test_forget_everything(tmp_path):
    m = store(tmp_path)
    m.remember("a fact one")
    m.remember("another different fact")
    assert len(m.forget("everything")) == 2 and m.facts() == []


def test_history_and_prompt_block(tmp_path):
    m = store(tmp_path)
    m.remember("Prince lives in Dhaka.")
    for i in range(10):
        m.add_exchange(f"question {i}", f"answer {i}")
    block = m.prompt_block()
    assert "Prince lives in Dhaka." in block
    assert "question 9" in block and "question 0" not in block  # only the last few
    assert "Never store passwords" in block


def test_tools(tmp_path):
    m = store(tmp_path)
    run = lambda c: asyncio.new_event_loop().run_until_complete(c)
    assert "Remembered" in run(RememberTool(store=m).execute(fact="Prince drinks tea."))
    assert "tea" in run(RecallTool(store=m).execute(query="tea"))
    assert "Forgot" in run(ForgetTool(store=m).execute(query="tea"))
    assert run(RecallTool(store=m).execute(query="tea")) == "No matching memories."


def test_agent_prompt_includes_memory_and_history_is_saved(tmp_path, monkeypatch):
    os.environ.setdefault("OPENMANUS_DISABLE_BROWSER_USE", "1")
    from fastapi.testclient import TestClient
    from openai.types.chat import ChatCompletionMessage

    import syrax.memory as memory_mod
    from syrax import server
    from syrax.brains import BrainRouter

    m = store(tmp_path)
    m.remember("Prince's favourite colour is crimson.")
    monkeypatch.setattr(memory_mod, "_store", m)
    seen = []

    async def fake(self, messages, system_msgs=None, **kw):
        seen.append(" ".join(str(getattr(x, "content", "") or "") for x in (system_msgs or [])))
        return ChatCompletionMessage(role="assistant", content="Crimson. Obviously.")

    monkeypatch.setattr(BrainRouter, "ask_tool", fake)
    with TestClient(server.app).websocket_connect("/ws", headers={"origin": "http://localhost:3000"}) as ws:
        while ws.receive_json().get("state") != "idle":
            pass
        ws.send_json({"type": "task", "text": "what is my favourite colour?"})
        while ws.receive_json()["type"] != "final":
            pass
    assert "favourite colour is crimson" in seen[0]
    assert m.recent()[-1] == {**m.recent()[-1], "user": "what is my favourite colour?", "reply": "Crimson. Obviously."}
    lines = (tmp_path / "history.jsonl").read_text().strip().splitlines()
    assert json.loads(lines[-1])["reply"] == "Crimson. Obviously."
