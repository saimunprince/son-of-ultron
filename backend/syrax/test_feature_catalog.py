"""The feature catalog and the prebuilt skills (2026-10-12): every entry is
well-formed and honest about its status; a TODO becomes an objective with its
own machine check; SYRAX takes up only low-risk entries that need nothing new;
shipped skills are installed and verified like SYRAX's own, never over a skill
SYRAX made itself. Throwaway journals and skill folders."""

import asyncio
import shutil
from pathlib import Path

import pytest

from app.tool.tool_collection import ToolCollection
from syrax import autonomy as auto
from syrax import catalog, permissions, prebuilt
from syrax.devloop import JUDGES
from syrax.journal import Journal
from syrax.server import OBJECTIVE_CHECKS
from syrax.skills import SkillFactory
from syrax.test_autonomy import make
from syrax.test_bridge import ORIGIN, TestClient, boot, recv_until, script, server  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
LOW = {permissions.READ_ONLY, permissions.WRITE, permissions.EXTERNAL_READ, permissions.SYSTEM}


def test_every_entry_is_well_formed_and_says_where_or_how():
    ids = [f.id for f in catalog.CATALOG]
    assert len(ids) == len(set(ids)) >= 60
    for f in catalog.CATALOG:
        assert f.area in catalog.AREAS and f.status in catalog.STATUSES and f.title and f.value and f.syrax, f.id
        if f.risk:
            assert f.risk in permissions.ORDER, f.id
        if f.status == catalog.TODO:
            assert f.check and f.check["kind"] in OBJECTIVE_CHECKS and f.risk, f.id  # provable, and its level is known
        if f.auto:
            assert f.status == catalog.TODO and not f.needs and f.risk in LOW and f.check["kind"] == "skill_verified", f.id


def test_the_prebuilt_features_are_marked_have_and_exist():
    shipped = {d.name for d in prebuilt.shipped()}
    assert {"weather", "screen_brightness", "wallpaper"} <= shipped
    cited = {f.id: f.syrax.split()[2] for f in catalog.CATALOG if f.status == catalog.HAVE and f.syrax.startswith("prebuilt skill ")}
    assert {"weather", "brightness", "wallpaper"} <= set(cited)
    assert all(name in shipped for name in cited.values()), cited  # a HAVE that names a prebuilt skill names one that ships


def test_a_todo_becomes_one_objective_with_its_own_check(tmp_path):
    j = Journal(tmp_path / "j.db")
    row = catalog.promote(j, "disk_usage")
    assert row["check_spec"] == {"kind": "skill_verified", "name": "disk_usage"} and row["key"] == "feature:disk_usage"
    assert "skill named `disk_usage`" in row["goal"] and "READ_ONLY" in row["goal"]
    assert catalog.promote(j, "disk_usage")["duplicate"]
    with pytest.raises(ValueError):
        catalog.promote(j, "weather")  # HAVE
    with pytest.raises(ValueError):
        catalog.promote(j, "power")  # REJECTED
    with pytest.raises(ValueError):
        catalog.promote(j, "live_voice", "catalog")  # needs a new dependency: only the human
    assert catalog.promote(j, "live_voice", "human")["key"] == "feature:live_voice"
    with pytest.raises(KeyError):
        catalog.promote(j, "teleport")


def test_syrax_takes_up_one_auto_feature_at_a_time(tmp_path):
    j = Journal(tmp_path / "j.db")
    first = catalog.next_auto(j)
    assert first is not None and first.auto
    catalog.promote(j, first.id, "catalog")
    assert catalog.next_auto(j) is None  # one feature objective open at a time
    o = j.objectives(status="OPEN")[0]
    j.update_objective_sync(o["id"], status="DONE", evidence={"proof": True})
    second = catalog.next_auto(j)
    assert second is not None and second.id != first.id


def test_the_idle_cycle_promotes_a_feature_only_when_the_service_asks(tmp_path, monkeypatch):
    j, core, a = make(tmp_path, tools=["terminate"])
    a.reflect = True
    a.set_enabled(True)
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    monkeypatch.setenv("SYRAX_RADAR", "0")
    monkeypatch.delenv("SYRAX_PUBLISH_RISE", raising=False)
    monkeypatch.delenv("SYRAX_CODEBENCH", raising=False)
    import syrax.limits as limits

    monkeypatch.setattr(limits, "choose", lambda journal, selfmodel: None)
    monkeypatch.delenv("SYRAX_FEATURES", raising=False)
    asyncio.run(a.run_once())
    assert not [o for o in j.objectives(limit=50) if str(o.get("key") or "").startswith("feature:")]
    monkeypatch.setenv("SYRAX_FEATURES", "1")
    rep = asyncio.run(a.run_once())
    promoted = [o for o in j.objectives(limit=50) if str(o.get("key") or "").startswith("feature:")]
    assert len(promoted) == 1 and promoted[0]["source"] == "catalog" and rep.derived >= 1


def test_the_catalog_document_is_generated_from_the_code():
    # git may check docs out with CRLF (core.autocrlf): compare the text, not the line endings
    doc = (ROOT / "docs" / "FEATURE_CATALOG.md").read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert doc == catalog.render()
    assert "no code was taken" in doc and "**auto**" in doc


def factory(tmp_path):
    j = Journal(tmp_path / "j.db")
    f = SkillFactory(j, root=tmp_path / "skills", task_id_provider=lambda: None)
    f.attach(ToolCollection())
    return j, f


def test_shipped_skills_are_installed_verified_and_registered(tmp_path):
    j, f = factory(tmp_path)
    done = asyncio.run(prebuilt.install(f))
    assert {d["skill"]: d["outcome"] for d in done} == {d.name: "VERIFIED" for d in prebuilt.shipped()}
    assert {"weather", "screen_brightness", "wallpaper"} <= set(f.collection.tool_map)
    assert permissions.level_of_tool("weather") == permissions.EXTERNAL_READ
    assert permissions.level_of_tool("screen_brightness") == permissions.SYSTEM and permissions.level_of_tool("wallpaper") == permissions.SYSTEM
    assert j.skill("weather")["purpose"].startswith("Current weather and a short forecast")
    ev = [e for e in j.recent_events(50) if e["type"] == "skill.prebuilt"]
    assert len(ev) == 1 and len(ev[0]["payload"]["skills"]) == len(prebuilt.shipped())
    again = asyncio.run(prebuilt.install(f))
    assert {d["outcome"] for d in again} == {"CURRENT"}  # nothing re-run


def test_a_skill_syrax_made_is_kept_and_a_changed_shipped_skill_is_updated(tmp_path):
    shipped = tmp_path / "prebuilt"
    shutil.copytree(prebuilt.PREBUILT_ROOT / "weather", shipped / "weather")
    j, f = factory(tmp_path)
    own = f.root / "wallpaper"
    own.mkdir(parents=True)
    (own / "skill.py").write_text("# SYRAX's own\n")
    shutil.copytree(prebuilt.PREBUILT_ROOT / "wallpaper", shipped / "wallpaper")
    done = {d["skill"]: d for d in asyncio.run(prebuilt.install(f, root=shipped))}
    assert done["wallpaper"]["outcome"] == "KEPT" and (own / "skill.py").read_text() == "# SYRAX's own\n"
    assert done["weather"]["outcome"] == "VERIFIED" and done["weather"]["installed"] == "new"
    p = shipped / "weather" / "skill.py"
    p.write_text(p.read_text(encoding="utf-8") + "\n# a newer shipped version\n", encoding="utf-8")
    done = {d["skill"]: d for d in asyncio.run(prebuilt.install(f, root=shipped))}
    assert done["weather"]["outcome"] == "VERIFIED" and done["weather"]["installed"] == "updated"
    assert (f.root / "weather" / "skill.py").read_text(encoding="utf-8").endswith("# a newer shipped version\n")


def test_a_broken_shipped_skill_is_never_registered(tmp_path):
    shipped = tmp_path / "prebuilt"
    shutil.copytree(prebuilt.PREBUILT_ROOT / "weather", shipped / "weather")
    t = shipped / "weather" / "test_skill.py"
    t.write_text(t.read_text(encoding="utf-8") + "\n\ndef test_broken():\n    assert False\n", encoding="utf-8")
    j, f = factory(tmp_path)
    done = asyncio.run(prebuilt.install(f, root=shipped))
    assert done[0]["outcome"] == "FAILED" and "weather" not in f.collection.tool_map


def test_the_ws_lists_features_and_the_human_promotes_one(script):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "features"})
        msg, _ = recv_until(ws, "features")
        assert len(msg["features"]) == len(catalog.CATALOG) and msg["counts"] == catalog.counts()
        ws.send_json({"type": "feature_promote", "id": "topic_monitor"})
        note, _ = recv_until(ws, "notice")
        assert note["text"].startswith("feature topic_monitor: objective #")
        ws.send_json({"type": "feature_promote", "id": "power"})
        note, _ = recv_until(ws, "notice")
        assert "REJECTED" in note["text"]


def test_the_catalog_and_the_installer_are_judges():
    assert "backend/syrax/catalog.py" in JUDGES and "backend/syrax/prebuilt.py" in JUDGES
