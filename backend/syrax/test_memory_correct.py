"""Memory correction (2026-10-25): the human rewrites one remembered fact in place from the memory panel. The row
keeps its id and type, takes the new text at confidence 1.0 with basis "human corrected (UI)", and `knowledge.updated`
journals `previous`; an empty text, a secret, or an id that is no remembered fact is refused. Over the WebSocket the
`memories` reply carries each fact's basis, confidence and type, `memory_correct` answers a notice and the refreshed
list, and `memory_export` answers `memory_exported {path, count}`."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from syrax import server
from syrax.journal import get_journal
from syrax.memory import CORRECTED_BASIS, CorrectRefused, MemoryStore
from syrax.test_bridge import ORIGIN, boot, recv_until, script  # noqa: F401  (the fixture is used by name)


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path / "memory.json", tmp_path / "history.jsonl")


def updates():
    return [e["payload"] for e in get_journal().recent_events(200) if e["type"] == "knowledge.updated"]


def test_correct_rewrites_the_text_keeps_the_type_and_journals_previous(store):
    store.remember("Prince prefers Vim.")
    fid = store.facts()[0]["id"]
    fact = store.correct(fid, "Prince prefers VS Code.")
    assert fact["id"] == fid and fact["text"] == "Prince prefers VS Code." and fact["type"] == "preference"
    assert fact["confidence"] == 1.0 and fact["basis"] == CORRECTED_BASIS
    row = get_journal().human_facts()[0]
    assert row["claim"] == "Prince prefers VS Code." and row["basis"] == CORRECTED_BASIS and "type:preference" in row["tags"]
    ev = updates()[-1]
    assert ev["previous"] == {"claim": "Prince prefers Vim.", "type": "preference", "confidence": 1.0}
    assert ev["claim"] == "Prince prefers VS Code." and ev["knowledge_id"] == int(fid)
    assert [f["text"] for f in store.facts()] == ["Prince prefers VS Code."]


def test_an_observation_corrected_by_the_human_keeps_its_type(store):
    store.remember("Prince usually works late.", "observation")
    fid = store.facts()[0]["id"]
    fact = store.correct(fid, "Prince usually works after midnight.")
    assert fact["type"] == "observation" and fact["basis"] == CORRECTED_BASIS and fact["confidence"] == 1.0
    assert updates()[-1]["previous"]["type"] == "observation"


def test_correct_refuses_empty_text_unknown_ids_other_kinds_and_secrets(store):
    store.remember("Prince lives in Dhaka.")
    fid = store.facts()[0]["id"]
    with pytest.raises(CorrectRefused, match="needs some text"):
        store.correct(fid, "   ")
    with pytest.raises(CorrectRefused, match="no remembered fact"):
        store.correct("999999", "Prince lives in Sylhet.")
    with pytest.raises(CorrectRefused, match="no remembered fact"):
        store.correct("not-an-id", "Prince lives in Sylhet.")
    with pytest.raises(CorrectRefused, match="secret"):
        store.correct(fid, "Prince's password is hunter2")
    # a knowledge row of another kind is not a remembered fact, whatever its id
    web = get_journal().add_knowledge_sync("Dhaka is the capital of Bangladesh.", "web", source_url="https://example.org/dhaka")
    with pytest.raises(CorrectRefused, match="no remembered fact"):
        store.correct(str(web["id"]), "Dhaka is a city.")
    assert [f["text"] for f in store.facts()] == ["Prince lives in Dhaka."] and updates() == []


def test_memories_carry_provenance_and_correct_and_export_work_over_the_websocket(script, tmp_path, monkeypatch):
    monkeypatch.setenv("SYRAX_EXPORT_DIR", str(tmp_path / "exports"))
    from syrax.memory import get_memory

    get_memory().remember("Prince prefers dark themes.")
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "memories"})
        mem, _ = recv_until(ws, "memories")
        f = mem["facts"][0]
        assert f["text"] == "Prince prefers dark themes." and f["type"] == "preference" and f["confidence"] == 1.0
        assert f["basis"] == "human said (remember tool)" and {"id", "created", "last_used", "uses"} <= set(f)
        ws.send_json({"type": "memory_correct", "id": f["id"], "text": "Prince prefers light themes."})
        notice, _ = recv_until(ws, "notice")
        assert notice["text"] == "Corrected: Prince prefers light themes."
        mem2, _ = recv_until(ws, "memories")
        assert [x["text"] for x in mem2["facts"]] == ["Prince prefers light themes."]
        assert mem2["facts"][0]["id"] == f["id"] and mem2["facts"][0]["basis"] == CORRECTED_BASIS
        ws.send_json({"type": "memory_correct", "id": f["id"], "text": ""})
        refused, _ = recv_until(ws, "notice")
        assert refused["text"].startswith("Refused")
        mem3, _ = recv_until(ws, "memories")
        assert [x["text"] for x in mem3["facts"]] == ["Prince prefers light themes."]
        ws.send_json({"type": "memory_export"})
        ex, _ = recv_until(ws, "memory_exported")
        assert ex["count"] == 1 and Path(ex["path"]).parent == tmp_path / "exports"
        doc = json.loads(Path(ex["path"]).read_text(encoding="utf-8"))
        assert doc["facts"][0]["text"] == "Prince prefers light themes." and doc["facts"][0]["basis"] == CORRECTED_BASIS
