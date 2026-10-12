"""Reminders: kept in the journal, fired once by SYRAX's own loop (also late,
after a restart), cancellable, and reaching the UI; the brain sets them with
the `remind` tool. No real notification is shown by these tests."""

import asyncio
import datetime as dt
import time

import pytest

from syrax import permissions, reminders
from syrax.journal import Journal
from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, get_journal, reply, script, server  # noqa: F401

NOW = dt.datetime(2026, 10, 12, 16, 0).timestamp()


def test_times_are_read_as_the_human_says_them():
    assert reminders.parse_when(in_minutes=10, now=NOW) == NOW + 600
    assert reminders.parse_when(at="17:30", now=NOW) == dt.datetime(2026, 10, 12, 17, 30).timestamp()
    assert reminders.parse_when(at="09:00", now=NOW) == dt.datetime(2026, 10, 13, 9, 0).timestamp()  # passed today: tomorrow
    assert reminders.parse_when(at="2026-10-14T08:15", now=NOW) == dt.datetime(2026, 10, 14, 8, 15).timestamp()
    for bad in ({"at": "2026-10-01T08:00"}, {"at": "noonish"}, {"in_minutes": 0}, {}):
        with pytest.raises(ValueError):
            reminders.parse_when(now=NOW, **bad)


def test_a_reminder_fires_once_in_order_and_late_ones_say_so(tmp_path):
    j = Journal(tmp_path / "j.db")
    a = reminders.create(j, "call Rahim", NOW + 60, now=NOW)
    b = reminders.create(j, "drink water", NOW + 30, now=NOW)
    c = reminders.create(j, "tomorrow thing", NOW + 86400, now=NOW)
    assert [r["id"] for r in reminders.pending(j)] == [b["id"], a["id"], c["id"]]
    shown = []

    async def notify(text):
        shown.append(text)

    assert asyncio.run(reminders.fire_due(j, notify, now=NOW + 10)) == []
    fired = asyncio.run(reminders.fire_due(j, notify, now=NOW + 600))
    assert [f["id"] for f in fired] == [b["id"], a["id"]] and fired[0]["late_s"] == 570
    assert shown == ["drink water (late by 9 min)", "call Rahim (late by 9 min)"]
    assert asyncio.run(reminders.fire_due(j, notify, now=NOW + 700)) == []  # never twice
    assert [r["id"] for r in reminders.pending(j)] == [c["id"]]


def test_the_list_survives_a_restart_and_cancel_works(tmp_path):
    j = Journal(tmp_path / "j.db")
    r = reminders.create(j, "stretch", time.time() + 3600)
    j.close()
    j2 = Journal(tmp_path / "j.db")
    assert [x["id"] for x in reminders.pending(j2)] == [r["id"]]
    assert reminders.cancel(j2, r["id"]) and not reminders.pending(j2)
    assert not reminders.cancel(j2, r["id"]) and not reminders.cancel(j2, "nope")


def test_a_failing_notification_never_loses_the_reminder(tmp_path):
    j = Journal(tmp_path / "j.db")
    r = reminders.create(j, "x", NOW + 1, now=NOW)

    async def broken(text):
        raise OSError("no tray")

    assert asyncio.run(reminders.fire_due(j, broken, now=NOW + 5))[0]["id"] == r["id"]
    assert [e["payload"]["id"] for e in j.events_of_type("reminder.fired")] == [r["id"]]


def test_the_tool_sets_lists_and_cancels(tmp_path):
    j = Journal(tmp_path / "j.db")
    tool = reminders.RemindTool(journal_provider=lambda: j)
    out = asyncio.run(tool.execute(action="set", text="call Rahim", in_minutes=30))
    assert out.error is None and out.output.startswith("Reminder ") and out.output.endswith(": call Rahim")
    rid = out.output.split()[1]
    assert rid in asyncio.run(tool.execute(action="list")).output
    assert asyncio.run(tool.execute(action="set", text="x")).error.startswith("remind: say when")
    assert asyncio.run(tool.execute(action="cancel", id=rid)).output == f"Reminder {rid} cancelled."
    assert asyncio.run(tool.execute(action="list")).output == "No pending reminders."
    assert permissions.level_of_tool("remind") == permissions.WRITE


def test_the_brain_sets_one_and_the_ui_hears_it_fire(script):
    script.queue = [call("remind", {"action": "set", "text": "call Rahim", "in_minutes": 5}), reply("Done: reminder set.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        hello = boot(ws)
        assert "remind" in hello["tools"]
        ws.send_json({"type": "task", "text": "Remind me in 5 minutes to call Rahim"})
        for _ in range(60):
            e = ws.receive_json()
            if e.get("type") == "task" and e.get("event") == "completed":
                break
    j = get_journal()
    (r,) = reminders.pending(j)
    assert r["text"] == "call Rahim"
    before = j.last_event_id()
    assert asyncio.run(reminders.fire_due(j, None, now=r["due_ts"] + 1))[0]["id"] == r["id"]
    (ev,) = [e for e in j.events_since(before) if e.type == "reminder.fired"]
    wire = ev.wire()  # what the UI receives through the journal fan-out
    assert wire["type"] == "reminder" and wire["event"] == "fired" and wire["text"] == "call Rahim"
