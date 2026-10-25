"""Memory export (2026-10-25): `MemoryStore.export` writes one JSON document with every remembered fact and its
provenance plus the conclusion/web knowledge rows with their sources; the default folder (backend/config/exports) is
gitignored; every string in the file goes through agent.py's CREDENTIAL mask; `python -m syrax.memory --export [path]`
does the same from the shell."""

import json
import re
from pathlib import Path

import pytest

from syrax import memory as memory_mod
from syrax.journal import get_journal
from syrax.memory import MemoryStore

REPO = Path(memory_mod.__file__).resolve().parents[2]


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path / "memory.json", tmp_path / "history.jsonl")


def test_export_writes_the_facts_with_provenance_and_the_count(store, tmp_path):
    store.remember("Prince lives in Dhaka.")
    store.remember("Prince prefers dark themes.")
    out = store.export(tmp_path / "out" / "memory.json")
    doc = json.loads(Path(out["path"]).read_text(encoding="utf-8"))
    assert set(doc) >= {"exported", "git_head", "count", "facts", "knowledge"}
    assert out["count"] == doc["count"] == len(doc["facts"]) == 2 and doc["knowledge"] == []
    f = {x["text"]: x for x in doc["facts"]}["Prince prefers dark themes."]
    assert set(f) >= {"id", "text", "type", "confidence", "basis", "created", "last_used", "uses"}
    assert f["type"] == "preference" and f["confidence"] == 1.0 and f["basis"] == "human said (remember tool)"
    assert not list((tmp_path / "out").glob("*.tmp"))  # written atomically: no temp file left behind


def test_the_default_export_lands_in_the_gitignored_exports_folder(store, tmp_path, monkeypatch):
    monkeypatch.setenv("SYRAX_EXPORT_DIR", str(tmp_path / "exports"))
    store.remember("Prince codes at night.")
    out = store.export()
    p = Path(out["path"])
    assert p.parent == tmp_path / "exports" and re.fullmatch(r"memory-\d{8}-\d{6}\.json", p.name)
    assert json.loads(p.read_text(encoding="utf-8"))["count"] == 1
    # the real default is backend/config/exports, and .gitignore lists exactly that folder
    monkeypatch.delenv("SYRAX_EXPORT_DIR")
    assert memory_mod.export_dir().resolve() == (REPO / "backend" / "config" / "exports").resolve()
    assert "backend/config/exports/" in (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_a_key_in_a_conclusion_row_is_masked_and_knowledge_comes_with_its_sources(store, tmp_path):
    store.remember("Prince's team uses Groq.")
    j = get_journal()
    web = j.add_knowledge_sync("Groq keys start with gsk_.", "web", source_url="https://console.groq.com/docs",
                               source_title="Groq docs")
    key = "gsk_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4"
    j.add_knowledge_sync(f"Deploy notes mention the staging key {key} for Groq.", "conclusion",
                         sources=[web["id"]], basis="SYRAX concluded (test)")
    out = store.export(tmp_path / "memory.json")
    raw = Path(out["path"]).read_text(encoding="utf-8")
    assert key not in raw and "[credential masked]" in raw
    doc = json.loads(raw)
    assert out["knowledge"] == doc["knowledge_count"] == 2 and {k["kind"] for k in doc["knowledge"]} == {"web", "conclusion"}
    concl = [k for k in doc["knowledge"] if k["kind"] == "conclusion"][0]
    assert concl["sources"] == [web["id"]] and concl["text"].endswith("[credential masked] for Groq.")
    assert concl["basis"] == "SYRAX concluded (test)" and {"confidence", "created", "last_used", "uses"} <= set(concl)
    assert [k for k in doc["knowledge"] if k["kind"] == "web"][0]["source_url"] == "https://console.groq.com/docs"
    assert doc["count"] == 1 and doc["facts"][0]["text"] == "Prince's team uses Groq."


def test_the_cli_exports_to_the_given_path(store, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(memory_mod, "_store", store)
    store.remember("Prince builds products.")
    target = tmp_path / "cli" / "mem.json"
    assert memory_mod.main(["--export", str(target)]) == 0
    assert json.loads(target.read_text(encoding="utf-8"))["count"] == 1
    assert str(target) in capsys.readouterr().out
    assert memory_mod.main([]) == 2  # no --export: usage, nothing written
