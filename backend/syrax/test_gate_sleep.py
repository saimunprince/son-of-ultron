"""Live 2026-10-17: the PC slept 69 minutes while objective 274's gate ran;
on wake the clock had moved past the 900 s timeout, pytest was killed as
"timeout after 900.0s", and a correct change was rolled back. Time the
machine slept does not count against a gate's timeout; a gate that really
runs too long still stops."""

import sys

from syrax import verify
from syrax.verify import Gate, run_gate


def test_a_gate_that_slept_is_not_timed_out(monkeypatch):
    clock = {"t": 1000.0, "calls": 0}

    def monotonic():
        clock["calls"] += 1
        if clock["calls"] == 3:  # one loop iteration lands an hour late: the machine slept
            clock["t"] += 3600.0
        clock["t"] += 0.5
        return clock["t"]

    monkeypatch.setattr(verify.time, "monotonic", monotonic)
    gate = Gate("short", [sys.executable, "-c", "import time; time.sleep(3); print('done')"], timeout=60.0)
    result = run_gate(gate)
    assert result.status == "PASS" and "done" in result.evidence


def test_a_gate_that_really_runs_too_long_still_stops():
    gate = Gate("long", [sys.executable, "-c", "import time; time.sleep(30)"], timeout=2.0)
    result = run_gate(gate)
    assert result.status == "NOT_VERIFIED" and "timeout after 2.0s" in result.evidence
