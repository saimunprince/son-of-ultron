"""scene (the Ultron comparison of 2026-10-31): one request sets the computer up for a kind of work. The tool only
names exact desktop calls; the owner's scenes.json overrides built-ins; steps outside STEP_ACTIONS are dropped."""

import asyncio
import json

from syrax import permissions, scenes


def test_requests_match_scenes_in_english_and_bengali():
    s = scenes.load(path="/nonexistent")
    assert scenes.match("coding mode on koro", s) == "coding"
    assert scenes.match("aaj porashona korbo", s) == "research"
    assert scenes.match("একটু গান শুনব", s) == "chill"
    assert scenes.match("what is the weather", s) is None
    assert scenes.match("encoding a file", s) is None  # a word inside another word is not a trigger


def test_the_owners_file_overrides_and_unsafe_steps_are_dropped(tmp_path):
    f = tmp_path / "scenes.json"
    f.write_text(json.dumps({
        "coding": {"triggers": ["dev"], "steps": [{"action": "launch_app", "target": "Terminal"}]},
        "evil": {"steps": [{"action": "trash", "target": "/home"}, {"action": "type_text", "value": "rm -rf"}]},
        "gaming": {"triggers": ["game"], "steps": [{"action": "launch_app", "target": "Steam"}, {"action": "click", "target": "1,1"}]},
    }))
    s = scenes.load(path=f)
    assert s["coding"]["steps"] == [{"action": "launch_app", "target": "Terminal"}]
    assert "evil" not in s and s["gaming"]["steps"] == [{"action": "launch_app", "target": "Steam"}]
    f.write_text("{broken")
    assert set(scenes.load(path=f)) == set(scenes.BUILT_IN)


def test_the_tool_names_calls_and_changes_nothing(monkeypatch):
    monkeypatch.setattr(scenes, "SCENES_FILE", scenes.Path("/nonexistent"))
    out = asyncio.run(scenes.SceneTool().execute(request="coding mode")).output
    assert "call `desktop` with {\"action\": \"launch_app\", \"target\": \"Visual Studio Code\"}" in out
    assert "coding" in asyncio.run(scenes.SceneTool().execute()).output
    assert asyncio.run(scenes.SceneTool().execute(request="fly to mars")).error
    assert permissions.level_of_tool("scene") == permissions.READ_ONLY
