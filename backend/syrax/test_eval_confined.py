"""Audit 2026-11-01 (self-improvement F6, quality run #15): a quality case's python_execute had the human's reach and
rewrote live code (self_patch_edit: open('backend/syrax/reminders.py', 'w')). Eval work is confined like SYRAX's
own autonomous work; it may write the workspace and the quality suite's own case folder."""

from syrax import tools


def test_eval_python_gets_own_works_confinement(tmp_path):
    spec = tools.confinement("eval", str(tmp_path / "out"), str(tmp_path), 30)
    assert spec.get("scrub_env") and "tcp_connect" in spec and spec.get("readable")
    human = tools.confinement("conversation", str(tmp_path / "out"), str(tmp_path), 30)
    assert "tcp_connect" not in human  # a human's request keeps its reach

