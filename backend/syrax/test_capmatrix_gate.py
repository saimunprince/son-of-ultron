"""The matrix's gate row judges the gate itself: every required check reached a
verdict and the gate passed a change within the window. Live 2026-10-15 the row
read RED because the last verification blocked SYRAX's own failing change."""

import time

from syrax import capmatrix as cm

DONE = {"py_compile": "PASS", "pytest": "FAIL", "tsc": "PASS", "diff_scan": "PASS", "performance": "PASS"}


def test_a_gate_that_blocked_a_failing_change_still_works():
    j = {"last_green_verification": {"id": 22, "ts": time.time() - 3600}}
    r, why = cm.live_checks(None, {"status": "BLOCKED", "gates": DONE}, j)["gate"]
    assert r == "pass" and "pytest FAIL" in why


def test_a_check_that_did_not_finish_or_no_recent_green_fails():
    j = {"last_green_verification": {"id": 22, "ts": time.time() - 3600}}
    crashed = dict(DONE, pytest="NOT_VERIFIED")
    r, why = cm.live_checks(None, {"status": "BLOCKED", "gates": crashed}, j)["gate"]
    assert r == "fail" and "did not reach a verdict" in why
    old = {"last_green_verification": {"id": 2, "ts": time.time() - 30 * 86400}}
    r, why = cm.live_checks(None, {"status": "BLOCKED", "gates": DONE}, old)["gate"]
    assert r == "fail" and "no GREEN verification" in why
    assert cm.live_checks(None, {"status": "GREEN", "gates": dict(DONE, pytest="PASS")}, {})["gate"][0] == "pass"
