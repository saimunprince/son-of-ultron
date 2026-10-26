"""The Windows CPU sampler keeps its previous GetSystemTimes reading and only
sleeps when it has no usable window.

Rule under test (sysinfo._win_cpu_percent):
  - first call (no previous reading): read, sleep sample_s, read;
  - previous reading at least _CPU_MIN_GAP_S old: no sleep, the percent is the
    average since that reading;
  - previous reading younger than _CPU_MIN_GAP_S: sleep again for a fresh
    window (chosen over returning the last value, so a percent always
    describes a window of real length);
  - every answer stays within 0..100.

GetSystemTimes and the clock are faked, so these run on any OS.
"""

from __future__ import annotations

import threading
import types

import pytest

from syrax import sysinfo

TICKS_PER_S = 10_000_000  # FILETIME ticks are 100 ns
CORES = 8


class FakeMachine:
    """A clock plus cumulative (idle, total) tick counters that advance with it."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.idle = 5 * TICKS_PER_S
        self.total = 10 * TICKS_PER_S
        self.busy = 0.5  # fraction busy while the clock runs
        self.sleeps: list = []
        self.reads = 0

    def run(self, seconds: float, busy: float = None) -> None:
        if busy is not None:
            self.busy = busy
        dt = int(seconds * TICKS_PER_S * CORES)
        self.now += seconds
        self.total += dt
        self.idle += int(dt * (1 - self.busy))

    # the hooks sysinfo calls
    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.run(seconds)

    def system_times(self):
        self.reads += 1
        return self.idle, self.total


@pytest.fixture
def machine(monkeypatch):
    m = FakeMachine()
    monkeypatch.setattr(sysinfo, "time", types.SimpleNamespace(monotonic=m.monotonic, sleep=m.sleep))
    monkeypatch.setattr(sysinfo, "_win_system_times", m.system_times)
    monkeypatch.setattr(sysinfo, "_cpu_last", None)
    return m


def test_first_call_samples_once_with_a_sleep(machine):
    machine.busy = 0.4
    pct = sysinfo._win_cpu_percent(sample_s=0.15)
    assert machine.sleeps == [0.15]
    assert machine.reads == 2
    assert pct == 40.0
    assert sysinfo._cpu_last == (machine.now, machine.idle, machine.total)


def test_later_call_uses_the_delta_since_the_previous_reading_without_sleeping(machine):
    sysinfo._win_cpu_percent()
    machine.sleeps.clear()
    machine.reads = 0
    machine.run(5.0, busy=0.25)
    assert sysinfo._win_cpu_percent() == 25.0
    assert machine.sleeps == []
    assert machine.reads == 1
    # the window then starts at that reading, not at the first one
    machine.run(0.1, busy=0.9)  # exactly the minimum gap still counts
    assert sysinfo._win_cpu_percent() == 90.0
    assert machine.sleeps == []
    assert machine.reads == 2


def test_call_too_soon_after_the_previous_reading_sleeps_for_a_fresh_window(machine):
    sysinfo._win_cpu_percent()
    machine.sleeps.clear()
    machine.reads = 0
    machine.run(0.05, busy=1.0)  # younger than _CPU_MIN_GAP_S
    machine.busy = 0.1  # what the fresh window sees
    pct = sysinfo._win_cpu_percent(sample_s=0.2)
    assert machine.sleeps == [0.2]
    assert machine.reads == 2
    assert pct == 10.0


def test_values_stay_within_0_and_100(machine, monkeypatch):
    sysinfo._win_cpu_percent()
    readings = iter([
        (machine.idle + 3 * TICKS_PER_S, machine.total + TICKS_PER_S),  # idle grew past total
        (machine.idle - 10 * TICKS_PER_S, machine.total + 2 * TICKS_PER_S),  # idle went backwards
        (machine.idle, machine.total - TICKS_PER_S),  # total went backwards
    ])
    monkeypatch.setattr(sysinfo, "_win_system_times", lambda: next(readings))
    got = []
    for _ in range(3):
        machine.now += 1.0
        got.append(sysinfo._win_cpu_percent())
    assert got == [0.0, 100.0, 0.0]
    monkeypatch.setattr(sysinfo, "_win_system_times", machine.system_times)
    sysinfo._cpu_last = (machine.now, machine.idle, machine.total)  # back to the real counters
    for busy in (0.0, 0.333, 1.0):
        machine.run(2.0, busy=busy)
        pct = sysinfo._win_cpu_percent()
        assert 0.0 <= pct <= 100.0
        assert pct == pytest.approx(busy * 100, abs=0.1)


def test_a_failed_read_answers_none(machine, monkeypatch):
    def broken():
        raise OSError("GetSystemTimes failed")

    monkeypatch.setattr(sysinfo, "_win_system_times", broken)
    assert sysinfo._win_cpu_percent() is None


def test_concurrent_callers_keep_the_newest_reading(machine):
    sysinfo._win_cpu_percent()
    machine.run(1.0, busy=0.6)
    out = []
    threads = [threading.Thread(target=lambda: out.append(sysinfo._win_cpu_percent())) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(out) == 8
    assert all(p is not None and 0.0 <= p <= 100.0 for p in out)
    assert sysinfo._cpu_last[0] == machine.now


def test_loadavg_on_windows_scales_the_sample_to_cores(machine, monkeypatch):
    monkeypatch.setattr(sysinfo, "WINDOWS", True)
    monkeypatch.setattr(sysinfo.os, "cpu_count", lambda: 4)
    sysinfo._win_cpu_percent()
    machine.sleeps.clear()
    machine.run(3.0, busy=0.5)
    assert sysinfo.loadavg() == [2.0, 2.0, 2.0]
    assert machine.sleeps == []
