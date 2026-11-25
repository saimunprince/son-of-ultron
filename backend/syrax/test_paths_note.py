"""Live 2026-11-25: the prompt called the workspace the working directory, code ran in backend/, and a path the human
gave from the project root was reported missing. The persona now names where code runs and the project root."""
import os
from pathlib import Path

from syrax import agent, prompt


def test_persona_names_where_code_runs_and_the_project_root():
    root = str(Path(prompt.__file__).resolve().parents[2])
    for persona in (prompt.SYRAX_PERSONA, prompt.SYRAX_PERSONA_SHORT):
        text = persona.format(directory="/ws")
        assert f"starts in: {os.getcwd()}" in text
        assert f"project root is: {root}" in text
        assert "before you say a file is missing" in text
        assert "working directory (workspace)" not in text


def test_step_check_points_at_the_latest_request():
    """"the original request" sent brains back to an earlier task; "Never undo" was answered as if it were the
    request ("No undo is required...")."""
    assert "latest request" in agent.STEP_PROMPT
    assert "original request" not in agent.STEP_PROMPT
    assert "undo" not in agent.STEP_PROMPT.lower()
    assert agent.STEP_PROMPT.startswith("[SYRAX step check, not a new request]")
