"""Live 2026-10-28: asked "What time is it now, and how long has this PC been up?", the brain read desktop
system_info (CPU, RAM, disk, uptime: no clock) and answered "Current time is 18:03" at 15:18 (UTC+06). Nothing it
had read said the time. Now system_info reads the clock like any other figure, and every task's prompt carries the
local time it started at with the rule to read the clock, never invent it."""

import asyncio
import datetime as dt
import os
import re

os.environ.setdefault("OPENMANUS_DISABLE_BROWSER_USE", "1")

from syrax.desktop import DesktopControl, local_clock  # noqa: E402
from syrax.test_bridge import core_mod, reply, script  # noqa: E402,F401  (script is a fixture)
from syrax.test_world_claims import run  # noqa: E402

CLOCK = re.compile(r"\w+day \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \(UTC[+-]\d{2}:\d{2}\)")


def test_local_clock_names_the_day_date_time_and_offset():
    t = dt.datetime(2026, 10, 28, 15, 18, 5, tzinfo=dt.timezone(dt.timedelta(hours=6)))
    assert local_clock(t) == "Wednesday 2026-10-28 15:18:05 (UTC+06:00)"
    assert CLOCK.fullmatch(local_clock())


def test_system_info_reads_the_clock_first():
    out = asyncio.new_event_loop().run_until_complete(DesktopControl().execute(action="system_info")).output
    first = out.splitlines()[0]
    assert first.startswith("Local time: ") and CLOCK.search(first)
    assert "RAM" in out and "Disk" in out  # the old readings are still there


def test_every_task_s_brain_gets_the_start_time_and_the_rule(script):
    script.queue = [reply("Hello.")]
    run("hi")
    system = core_mod.get_core().agent.system_prompt
    assert re.search(r"This task started at " + CLOCK.pattern, system)
    assert "never state a time or date you did not read" in system
