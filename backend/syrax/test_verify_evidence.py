"""Live 2026-11-04: a BLOCKED pytest gate was blamed on warnings; the FAILED lines had fallen out of the last 40 lines."""

from syrax import verify


def test_failing_tests_stay_in_the_evidence_ahead_of_the_tail():
    out = "\n".join(["collected 2900 items", "FAILED syrax/test_camera.py::test_x - AssertionError",
                     "ERROR syrax/test_y.py - ImportError"] + [f"warning line {i}" for i in range(60)])
    ev = verify._tail(out)
    lines = ev.splitlines()
    assert lines[0].startswith("FAILED syrax/test_camera.py") and lines[1].startswith("ERROR syrax/test_y.py")
    assert lines[2] == "..." and lines[-1] == "warning line 59" and len(lines) == 3 + verify.TAIL_LINES


def test_a_short_or_clean_output_is_unchanged():
    assert verify._tail("1 passed in 0.1s") == "1 passed in 0.1s"
    out = "\n".join(f"line {i}" for i in range(50))
    assert verify._tail(out) == "\n".join(f"line {i}" for i in range(10, 50))


def test_the_agent_is_told_not_to_promise_and_how_to_read_a_failed_gate():
    from syrax.agent import TOOLS_GUIDE

    assert "Never promise to do something later" in TOOLS_GUIDE and "pushing to GitHub is the owner's setting" in TOOLS_GUIDE
    assert "warnings never fail a gate" in TOOLS_GUIDE
