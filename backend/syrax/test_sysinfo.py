"""The machine facts every reader (resource gate, self-model, desktop tool)
gets from sysinfo have the same shape on Linux and Windows."""

import os

from syrax import sysinfo


def test_meminfo_reports_this_machine():
    mem = sysinfo.meminfo()
    assert set(mem) == {"total_mb", "available_mb"}
    assert mem["total_mb"] and mem["total_mb"] > 256
    assert 0 <= mem["available_mb"] <= mem["total_mb"]


def test_loadavg_has_three_values_or_none():
    load = sysinfo.loadavg()
    assert load is None or (len(load) == 3 and all(x >= 0 for x in load))
    if load is not None:
        assert load[0] <= (os.cpu_count() or 1) * 4  # a sane bound on any laptop


def test_battery_shape():
    bat = sysinfo.battery()
    assert bat is None or (set(bat) == {"percent", "status", "discharging"} and 0 <= bat["percent"] <= 100)


def test_uptime_is_positive_or_unknown():
    up = sysinfo.uptime_seconds()
    assert up is None or up > 0
