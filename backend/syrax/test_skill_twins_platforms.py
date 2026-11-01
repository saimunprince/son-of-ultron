"""Audit 2026-11-01 (skills S12, S13): duplicate checks compared only VERIFIED skills, so a twin of a skill the human
had turned off was built at once (flight_search disabled, flight_query created); and Windows-only skill code that
declared no platforms was a VERIFIED tool on Linux. A twin of a FAILED skill is refused (fix that one); a twin of a
DISABLED skill stays allowed by contract (test_skill_lifecycle). Windows- or macOS-only code is recognised unless it
checks the platform itself."""

import asyncio
import sys

import pytest

from syrax.skills import inferred_platforms, platform_problem
from syrax.test_skills import GOOD, GOOD_TEST, factory


def test_a_twin_of_a_failed_skill_is_refused(tmp_path):
    j, f, coll = factory(tmp_path)
    asyncio.run(f.create("word_count", "count the words in a text", GOOD, GOOD_TEST))
    j.set_skill_status_sync("word_count", "FAILED", note="broken")
    with pytest.raises(ValueError, match="failed its tests: word_count"):
        asyncio.run(f.create("count_words", "count the words in a text", GOOD.replace("word_count", "count_words"), GOOD_TEST))


def test_platform_only_code_is_recognised():
    assert inferred_platforms("import ctypes\nctypes.windll.user32.SystemParametersInfoW(0)") == ("win32",)
    assert inferred_platforms("subprocess.run(['osascript', '-e', 'beep'])") == ("darwin",)
    assert inferred_platforms("if sys.platform == 'win32':\n    ctypes.windll") == ()  # it checks for itself
    assert inferred_platforms("import requests") == ()

    class T:
        pass

    why = platform_problem(T(), "ctypes.windll.user32")
    assert (why is None) == sys.platform.startswith("win")
