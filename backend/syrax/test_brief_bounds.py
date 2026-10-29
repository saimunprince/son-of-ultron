"""Live 2026-10-29 (autonomy at level 3): asked to verify organize_folder, the brain pointed it at ~/Desktop and the
kernel boundary refused (correctly), costing an attempt; asked to verify flight_search, nothing told it why config
reads failed. Every own task's brief now says where its code may reach, and the operator's autonomy level."""

import asyncio

from syrax import autonomy as auto
from syrax.permissions import WORKSPACE
from syrax.test_autonomy import make


def test_the_brief_states_the_boundary_and_the_level(tmp_path, monkeypatch):
    j, core, a = make(tmp_path, tools=["organize_folder", "terminate"])
    monkeypatch.setattr(auto, "resource_pressure", lambda: None)
    a.set_enabled(True)
    a.set_level(3, "test")
    j.add_objective_sync("Verify that the `organize_folder` tool works on this machine", reason="unverified", priority=1,
                         check={"kind": "tool_verified", "tool": "organize_folder"})
    asyncio.run(a.run_once())
    brief = core.submitted[0][1]
    assert f"writes only in the workspace {WORKSPACE}" in brief and "out of reach" in brief
    assert "autonomy level to 3 (modify and verify)" in brief
    assert "make inside the workspace" in brief  # the tool_verified hint
