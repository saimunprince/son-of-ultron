"""The routines engine (2026-11-25, idea from the Mark-LVII JARVIS project): monthly and interval rules, weekdays,
the lateness limit (skip, never a burst), quiet hours for untimed rules, task routines that run unattended as the
autonomous kind, and old reminder rows that load and fire unchanged. No real notification or task is started."""

import asyncio
import datetime as dt

import pytest

from syrax import estop, permissions, reminders
from syrax.journal import Journal

NOW = dt.datetime(2026, 10, 12, 16, 0).timestamp()  # a Monday


def T(*a):
    return dt.datetime(*a).timestamp()


def fire(j, now, start_task=None):
    return asyncio.run(reminders.fire_due(j, None, now=now, start_task=start_task))


def only_pending(j):
    (r,) = reminders.pending(j)
    return r


def test_monthly_on_the_31st_fires_on_a_short_months_last_day(tmp_path):
    j = Journal(tmp_path / "j.db")
    r = reminders.create(j, "pay rent", reminders.parse_when(at="09:00", now=NOW), now=NOW, repeat="monthly", day="31")
    assert r["due_ts"] == T(2026, 10, 31, 9, 0) and r["day"] == 31
    for want in (T(2026, 11, 30, 9, 0), T(2026, 12, 31, 9, 0), T(2027, 1, 31, 9, 0), T(2027, 2, 28, 9, 0), T(2027, 3, 31, 9, 0)):
        assert len(fire(j, only_pending(j)["due_ts"] + 1)) == 1
        assert only_pending(j)["due_ts"] == want


def test_monthly_last_day_and_the_day_of_at(tmp_path):
    j = Journal(tmp_path / "j.db")
    r = reminders.create(j, "close books", reminders.parse_when(at="18:00", now=NOW), now=NOW, repeat="monthly", day="last")
    assert r["due_ts"] == T(2026, 10, 31, 18, 0)
    fire(j, r["due_ts"] + 1)
    assert only_pending(j)["due_ts"] == T(2026, 11, 30, 18, 0)
    k = reminders.create(j, "invoice", T(2026, 10, 20, 10, 0), now=NOW, repeat="monthly")  # the day comes from `at`
    assert k["day"] == 20 and k["due_ts"] == T(2026, 10, 20, 10, 0)
    with pytest.raises(ValueError):
        reminders.create(j, "x", NOW + 60, now=NOW, repeat="monthly", day="32")


def test_interval_runs_inside_its_window_and_moves_to_the_next_day(tmp_path):
    j = Journal(tmp_path / "j.db")
    r = reminders.create(j, "drink water", None, now=NOW, repeat="interval", every_min=30, between="09:00-17:00")
    assert r["due_ts"] == T(2026, 10, 12, 16, 30) and r["untimed"] is True
    fire(j, r["due_ts"] + 1)
    assert only_pending(j)["due_ts"] == T(2026, 10, 12, 17, 0)
    fire(j, T(2026, 10, 12, 17, 0, 1))
    assert only_pending(j)["due_ts"] == T(2026, 10, 13, 9, 0)
    early = reminders.create(j, "y", None, now=T(2026, 10, 13, 7, 0), repeat="interval", every_min=45, between="09:00-17:00")
    assert early["due_ts"] == T(2026, 10, 13, 9, 0)
    for bad in ({"every_min": 2}, {"every_min": 30, "between": "17:00-09:00"}, {"every_min": None},
                {"every_min": 5, "between": "00:00-23:59"}):  # the last: too many runs a day
        with pytest.raises(ValueError):
            reminders.create(j, "x", None, now=NOW, repeat="interval", **bad)


def test_weekdays_limit_interval_and_daily_rules(tmp_path):
    j = Journal(tmp_path / "j.db")
    fri_end = T(2026, 10, 16, 16, 30)
    r = reminders.create(j, "stand up", None, now=fri_end - 60, repeat="interval", every_min=30, between="09:00-17:00",
                         weekdays="mon-fri")
    assert r["weekdays"] == [0, 1, 2, 3, 4] and r["due_ts"] == fri_end
    fire(j, fri_end + 1)
    fire(j, T(2026, 10, 16, 17, 0, 1))
    assert only_pending(j)["due_ts"] == T(2026, 10, 19, 9, 0)  # Saturday and Sunday passed over
    reminders.cancel(j, only_pending(j)["id"])
    d = reminders.create(j, "long walk", reminders.parse_when(at="08:00", now=NOW), now=NOW, repeat="daily", weekdays="sat,sun")
    assert d["due_ts"] == T(2026, 10, 17, 8, 0)
    fire(j, d["due_ts"] + 1)
    assert only_pending(j)["due_ts"] == T(2026, 10, 18, 8, 0)
    fire(j, T(2026, 10, 18, 8, 0, 1))
    assert only_pending(j)["due_ts"] == T(2026, 10, 24, 8, 0)
    with pytest.raises(ValueError):
        reminders.create(j, "x", NOW + 60, now=NOW, repeat="weekly", weekdays="mon")


def test_a_run_past_its_lateness_limit_is_skipped_and_journaled(tmp_path):
    j = Journal(tmp_path / "j.db")
    once = reminders.create(j, "call Rahim", NOW + 60, now=NOW)
    assert fire(j, NOW + 60 + 3 * 3600) == []  # speak: 2 h limit
    (s,) = j.events_of_type("reminder.skipped")
    assert s["payload"]["id"] == once["id"] and s["payload"]["late_s"] == 3 * 3600 and not reminders.pending(j)
    started = []

    async def runner(instruction):
        started.append(instruction)
        return "t1"

    reminders.create(j, "backup notes", NOW + 60, now=NOW, task="copy notes to backup")
    assert fire(j, NOW + 60 + 5 * 3600, runner)[0]["task_id"] == "t1"  # task: 6 h limit, 5 h late still runs
    reminders.create(j, "backup notes", NOW + 60, now=NOW, task="copy notes to backup")
    assert fire(j, NOW + 60 + 7 * 3600, runner) == [] and started == ["copy notes to backup"]


def test_a_repeating_rule_never_fires_a_burst_of_missed_runs(tmp_path):
    j = Journal(tmp_path / "j.db")
    reminders.create(j, "drink water", None, now=NOW, repeat="interval", every_min=30, between="09:00-17:00")
    # off for 90 minutes the next morning: three runs missed, one fires, the next run is after now
    back = T(2026, 10, 13, 10, 30, 5)
    reminders.cancel(j, only_pending(j)["id"])
    reminders.create(j, "drink water", None, now=T(2026, 10, 13, 8, 0), repeat="interval", every_min=30, between="09:00-17:00")
    assert len(fire(j, back)) == 1 and fire(j, back) == []
    assert only_pending(j)["due_ts"] == T(2026, 10, 13, 11, 0)
    # off for three days: nothing fires, one skip, one next run
    gone = T(2026, 10, 16, 12, 10)
    assert fire(j, gone) == [] and fire(j, gone) == []
    assert len(j.events_of_type("reminder.skipped")) == 1
    assert only_pending(j)["due_ts"] == T(2026, 10, 16, 12, 30)


def test_quiet_hours_hush_untimed_rules_but_not_a_timed_reminder(tmp_path, monkeypatch):
    j = Journal(tmp_path / "j.db")
    monkeypatch.delenv("SYRAX_QUIET_HOURS", raising=False)
    day0 = T(2026, 10, 13, 5, 0)
    reminders.create(j, "stretch", None, now=day0, repeat="interval", every_min=30, between="06:00-08:00")
    timed = reminders.create(j, "take pills", reminders.parse_when(at="06:00", now=day0), now=day0)
    monkeypatch.setenv("SYRAX_QUIET_HOURS", "23:00-07:00")
    fired = fire(j, T(2026, 10, 13, 6, 0, 5))
    assert [f["id"] for f in fired] == [timed["id"]]  # the explicitly timed one still rings
    (s,) = j.events_of_type("reminder.skipped")
    assert s["payload"]["reason"] == "quiet hours" and s["payload"]["text"] == "stretch"
    fire(j, T(2026, 10, 13, 6, 30, 5))
    assert fire(j, T(2026, 10, 13, 7, 0, 5))[0]["text"] == "stretch"  # quiet hours over
    monkeypatch.delenv("SYRAX_QUIET_HOURS")
    assert fire(j, T(2026, 10, 13, 7, 30, 5))[0]["text"] == "stretch"  # off by default


class FakeCore:
    def __init__(self, journal, busy=False):
        self.journal, self.busy, self.calls = journal, busy, []

    async def submit(self, goal, said, session_id, kind="conversation", **kw):
        self.calls.append({"goal": goal, "said": said, "session_id": session_id, "kind": kind})
        return "task-1"


def test_a_task_routine_runs_unattended_as_the_autonomous_kind(tmp_path):
    j = Journal(tmp_path / "j.db")
    core = FakeCore(j)
    assert asyncio.run(reminders.start_routine_task(core, "tidy the downloads folder")) == "task-1"
    (c,) = core.calls
    assert c["kind"] == reminders.ROUTINE_KIND == "autonomous" and c["said"] == "tidy the downloads folder"
    assert c["session_id"] is None and c["goal"].startswith("tidy the downloads folder") and "nobody is watching" in c["goal"]
    # that kind refuses what nobody watching may do, even when the instruction names it
    for level in (permissions.DESTRUCTIVE, permissions.EXTERNAL_WRITE, permissions.SYSTEM):
        d = permissions.Decision(tool="shell", level=level, reason="rm -rf ~/Downloads")
        assert permissions.decide(d, reminders.ROUTINE_KIND, "rm -rf ~/Downloads").action == "refuse"
    assert asyncio.run(reminders.start_routine_task(FakeCore(j, busy=True), "x")) is None
    estop.set_stop(j, "test", "test")
    with pytest.raises(PermissionError):
        asyncio.run(reminders.start_routine_task(core, "x"))


def test_a_task_routine_waits_while_busy_and_skips_on_the_stop(tmp_path):
    j = Journal(tmp_path / "j.db")
    r = reminders.create(j, "weekly report", NOW + 60, now=NOW, repeat="weekly", task="write the weekly report")
    assert r["action"] == "task" and r["task"] == "write the weekly report"
    answers = [None, "t9"]

    async def runner(instruction):
        return answers.pop(0)

    assert fire(j, NOW + 120, runner) == [] and only_pending(j)["id"] == r["id"]  # busy: nothing journaled, waits
    (f,) = fire(j, NOW + 135, runner)
    assert f["action"] == "task" and f["task_id"] == "t9"
    nxt = only_pending(j)
    assert nxt["action"] == "task" and nxt["task"] == "write the weekly report"

    async def stopped(instruction):
        raise PermissionError("the emergency stop is on")

    assert fire(j, nxt["due_ts"] + 1, stopped) == []
    assert j.events_of_type("reminder.skipped")[-1]["payload"]["reason"] == "task refused: the emergency stop is on"
    assert fire(j, only_pending(j)["due_ts"] + 1) == []  # no runner wired: skipped, never spoken instead
    assert j.events_of_type("reminder.skipped")[-1]["payload"]["reason"] == "no task runner"


def test_old_rows_load_and_fire_unchanged(tmp_path):
    j = Journal(tmp_path / "j.db")
    old_once = {"id": "aaaa1111", "text": "call Rahim", "due_ts": NOW + 60, "created_ts": NOW}
    old_daily = {"id": "bbbb2222", "text": "drink water", "due_ts": NOW + 30, "created_ts": NOW, "repeat": "daily"}
    j.record_sync("reminder.created", old_once)
    j.record_sync("reminder.created", old_daily)
    assert reminders.pending(j) == [old_daily, old_once]
    assert [f["id"] for f in fire(j, NOW + 600)] == ["bbbb2222", "aaaa1111"]
    nxt = only_pending(j)
    assert set(nxt) == {"id", "text", "due_ts", "created_ts", "repeat"} and nxt["due_ts"] == pytest.approx(NOW + 30 + 86400)
    new = reminders.create(j, "stretch", NOW + 60, now=NOW, repeat="weekly")
    assert set(new) == {"id", "text", "due_ts", "created_ts", "repeat"}  # new once/daily/weekly rows keep the old format
    assert reminders.next_due(NOW, "daily", NOW + 3 * 86400 + 5) == pytest.approx(NOW + 4 * 86400)


def test_the_tool_sets_the_new_rules(tmp_path):
    j = Journal(tmp_path / "j.db")
    tool = reminders.RemindTool(journal_provider=lambda: j)
    props = tool.parameters["properties"]
    assert {"day", "every_minutes", "between", "weekdays", "task"} <= set(props) and "interval" in props["repeat"]["enum"]
    out = asyncio.run(tool.execute(action="set", text="drink water", repeat="interval", every_minutes=30,
                                   between="09:00-17:00", weekdays="mon-fri"))
    assert out.error is None and "then every 30 min 09:00-17:00 on mon,tue,wed,thu,fri: drink water" in out.output
    out = asyncio.run(tool.execute(action="set", text="pay rent", at="09:00", repeat="monthly", day="last"))
    assert out.error is None and "then monthly on day last" in out.output
    out = asyncio.run(tool.execute(action="set", text="report", at="09:00", repeat="weekly", task="write the weekly report"))
    assert out.error is None and "(starts a task)" in out.output
    listed = asyncio.run(tool.execute(action="list")).output
    assert listed.count("\n") == 2 and "(starts a task) · report" in listed
    assert "every_minutes" in asyncio.run(tool.execute(action="set", text="x", repeat="interval")).error
