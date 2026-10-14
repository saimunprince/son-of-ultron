"""Visible Work Presence: the human's "hide" / "show" / "go minimal" set the
level SYRAX's faces show; a visibility command is never a task, works while a
task runs, is journaled and kept across restarts."""

import asyncio

import pytest

from syrax import presence
from syrax.journal import Journal
from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, get_journal, recv_until, reply, script, server  # noqa: F401


@pytest.mark.parametrize("text,level", [
    ("hide", "hidden"), ("Hide.", "hidden"), ("syrax, hide yourself", "hidden"), ("go away", "hidden"),
    ("show", "visible"), ("show yourself", "visible"), ("come back", "visible"), ("fullscreen", "visible"),
    ("go minimal", "minimal"), ("minimise", "minimal"), ("corner mode", "minimal"),
])
def test_short_commands_name_a_level(text, level):
    assert presence.parse_command(text) == level


@pytest.mark.parametrize("text", ["hide the file secret.txt from the folder", "show me the weather in Dhaka", "what can you show me?",
                                  "minimal python example please", ""])
def test_anything_else_is_not_a_visibility_command(text):
    assert presence.parse_command(text) is None


def test_the_level_is_journaled_and_survives_a_restart(tmp_path):
    j = Journal(tmp_path / "j.db")
    p = presence.Presence(j)
    assert p.visibility == "visible"
    snap = asyncio.run(p.set("minimal", by="text"))
    assert snap == {"visibility": "minimal", "levels": ["visible", "minimal", "hidden"]}
    ev = j.events_of_type("presence.changed", limit=5)
    assert ev and ev[-1]["payload"] == {"visibility": "minimal", "before": "visible", "by": "text"}
    assert presence.Presence(j).visibility == "minimal"  # a new core reads it back
    with pytest.raises(ValueError):
        asyncio.run(p.set("invisible"))


def test_hide_over_the_socket_is_not_a_task_and_reaches_every_face(script):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        hello = boot(ws)
        assert hello["presence"]["visibility"] in presence.LEVELS
        before = len(get_journal().tasks(limit=500))
        ws.send_json({"type": "task", "text": "hide"})
        ev, _ = recv_until(ws, "presence")
        assert ev["visibility"] == "hidden" and ev["event"] == "changed" and ev["by"] == "text"
        assert len(get_journal().tasks(limit=500)) == before  # no task was started
        ws.send_json({"type": "presence", "visibility": "visible"})
        ev, _ = recv_until(ws, "presence")
        assert ev["visibility"] == "visible" and ev["by"] == "ui"
        ws.send_json({"type": "presence", "visibility": "nope"})
        note, _ = recv_until(ws, "notice")
        assert "visibility must be one of" in note["text"]
    assert core_mod.get_core().snapshot()["presence"]["visibility"] == "visible"
