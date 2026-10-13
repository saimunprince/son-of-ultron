"""Phase 2 of the self-improvement plan: the owner names the brain for SYRAX's own
code changes (brains.json: self_change_brain). A release task tries it first;
when it cannot take the call the benchmark's choice stands in and the journal
says why. Nothing else about routing changes."""

import asyncio
import json
import time

from syrax import brains, core as core_mod
from syrax.brains import BrainStore, Health, PROVIDERS, get_router
from syrax.journal import Journal
from syrax.test_codebench import Router, bench


def test_the_store_keeps_the_choice_and_drops_an_unknown_one(tmp_path, monkeypatch):
    monkeypatch.setattr(brains, "BRAINS_FILE", tmp_path / "brains.json")
    s = BrainStore()
    s.self_change_brain = "groq"
    s.save()
    assert json.loads((tmp_path / "brains.json").read_text())["self_change_brain"] == "groq"
    assert BrainStore.load().self_change_brain == "groq"
    (tmp_path / "brains.json").write_text(json.dumps({"order": [], "providers": {}, "self_change_brain": "nope"}))
    assert BrainStore.load().self_change_brain is None


def test_update_sets_clears_and_ignores_unknown_and_describe_shows_it(tmp_path, monkeypatch):
    monkeypatch.setattr(brains, "BRAINS_FILE", tmp_path / "brains.json")
    r = brains.BrainRouter.__new__(brains.BrainRouter)
    r.store, r.health, r.active = BrainStore(), {p: Health() for p in PROVIDERS}, None
    r.update({}, None)  # nothing passed: untouched
    assert r.store.self_change_brain is None
    r.update({}, None, self_change_brain="gemini")
    assert r.store.self_change_brain == "gemini" and r.describe()["self_change_brain"] == "gemini"
    r.update({}, None, self_change_brain="unknown-brain")
    assert r.store.self_change_brain == "gemini"  # ignored, not saved
    r.update({}, None, self_change_brain="")
    assert r.store.self_change_brain is None
    r.store.get("gemini")["api_key"] = "k"
    assert r.usable("gemini") == (True, "ready")
    r.health["gemini"] = Health(time.time() + 60, "429")
    assert r.usable("gemini") == (False, "cooldown: 429")
    r.store.get("gemini")["enabled"] = False
    assert r.usable("gemini") == (False, "disabled")
    assert r.usable("anthropic")[1] == "no key"


def _stub(j):
    return type("C", (), {"journal": j})()


def test_a_release_task_tries_the_owners_brain_first_and_journals_it(tmp_path, monkeypatch):
    j = Journal(tmp_path / "j.db")
    bench(j, "alpha", 4, 0)
    bench(j, "beta", 4, 4)
    router = Router(["alpha", "beta"])
    router.store.self_change_brain = "alpha"
    router.usable = lambda pid: (True, "ready")
    monkeypatch.setattr(core_mod, "get_router", lambda: router)
    t = j.start_task_sync("x", kind="autonomous")
    asyncio.run(core_mod.Core._route(_stub(j), "edit the file", t, release=True))
    assert router.routed == "alpha"  # the owner's choice, not the benchmark's beta
    ev = [e for e in j.events(t) if e["type"] == "brain.routed"][-1]["payload"]
    assert ev == {"kind": "code_change", "brain": "alpha", "instead_of": "alpha", "reason": "self_change_brain"}
    asyncio.run(core_mod.Core._route(_stub(j), "what is the capital of Japan", t, release=False))
    assert router.routed is None  # conversation and other work: untouched


def test_when_the_owners_brain_cannot_take_the_call_the_benchmark_stands_in_and_the_journal_says_why(tmp_path, monkeypatch):
    j = Journal(tmp_path / "j.db")
    bench(j, "alpha", 4, 0)
    bench(j, "beta", 4, 4)
    router = Router(["alpha", "beta"])
    router.store.self_change_brain = "gamma"  # set, but not enabled in the order
    router.usable = lambda pid: (False, "cooldown: 429")
    monkeypatch.setattr(core_mod, "get_router", lambda: router)
    t = j.start_task_sync("x", kind="autonomous")
    asyncio.run(core_mod.Core._route(_stub(j), "edit the file", t, release=True))
    assert router.routed == "beta"
    ev = [e for e in j.events(t) if e["type"] == "brain.routed"][-1]["payload"]
    assert ev["brain"] == "beta" and ev["instead_of"] == "gamma" and ev["reason"] == "self_change_brain gamma unavailable (cooldown: 429); fallback"


def test_the_live_router_round_trips_through_update(tmp_path, monkeypatch):
    monkeypatch.setattr(brains, "BRAINS_FILE", tmp_path / "brains.json")
    r = get_router()
    before = r.store.self_change_brain
    try:
        r.update({}, None, self_change_brain="groq")
        assert r.describe()["self_change_brain"] == "groq"
    finally:
        r.update({}, None, self_change_brain=before)
