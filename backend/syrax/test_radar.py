"""Phase 6: the technology radar finds new models and tests only those."""

import asyncio
import os

os.environ.setdefault("OPENMANUS_DISABLE_BROWSER_USE", "1")

from syrax import radar  # noqa: E402
from syrax.journal import Journal  # noqa: E402


class Store:
    def __init__(self, models):
        self.order, self._models = list(models), models

    def enabled(self, pid):
        return True

    def model(self, pid):
        return "current-model"


class Router:
    def __init__(self, catalog):
        self.catalog = catalog
        self.store = Store(catalog)
        self.tested = []

    async def list_models(self, pid):
        return list(self.catalog[pid])

    async def test(self, pid, model=None):
        self.tested.append(model)
        return {"id": pid, "ok": True, "tools": model != "no-tools:free", "latency_ms": 900}


def test_first_scan_is_a_baseline_then_only_new_models_are_tested(tmp_path):
    j = Journal(tmp_path / "j.db")
    r = Router({"openrouter": ["a:free", "b:free"]})
    first = asyncio.run(radar.scan(r, j))
    assert first["baselined"] == ["openrouter"] and r.tested == []  # no catalogue-wide testing
    r.catalog["openrouter"] = ["a:free", "b:free", "new-big:free", "no-tools:free"]
    second = asyncio.run(radar.scan(r, j))
    assert second["new"]["openrouter"] == ["new-big:free", "no-tools:free"] and r.tested == ["new-big:free", "no-tools:free"]
    props = [e["payload"] for e in j.recent_events(100) if e["type"] == "proposal.created"]
    assert len(props) == 1 and "new-big:free" in props[0]["proposal"] and props[0]["kind"] == "technology_radar"
    assert not radar.due(j)  # once a day


def test_testing_budget_is_capped(tmp_path):
    j = Journal(tmp_path / "j.db")
    r = Router({"openrouter": ["a"]})
    asyncio.run(radar.scan(r, j))
    r.catalog["openrouter"] = ["a"] + [f"m{i}" for i in range(10)]
    out = asyncio.run(radar.scan(r, j))
    assert len(out["tested"]) == radar.MAX_TESTS and len(out["new"]["openrouter"]) == 10
