"""Audit 2026-11-01 (I-12): a SYRAX browser left by a crashed SYRAX was adopted (its debug port answered) and never
closed: `_proc` stayed None, so shutdown did nothing, and that Chrome outlived every later SYRAX. The browser's pid
is kept in the profile; an adopted browser is closed at shutdown, but only when that pid is still our profile's
Chrome (a reused pid is never killed)."""

import asyncio
import subprocess
import sys

import pytest

from syrax import browser


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setattr(browser, "PROFILE", tmp_path / "prof")
    monkeypatch.setattr(browser, "MANAGED", True)
    monkeypatch.setattr(browser, "_proc", None)
    monkeypatch.setattr(browser, "_adopted", None)
    (tmp_path / "prof").mkdir()
    return tmp_path / "prof"


def _sleeper(profile):
    # stands in for Chrome: a process whose command line names the profile, in its own session like Chrome's
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", f"--user-data-dir={profile}"],
                            start_new_session=True)


async def _up():
    return True


@pytest.mark.skipif(sys.platform == "win32", reason="process groups")
def test_an_adopted_browser_is_closed_at_shutdown(profile, monkeypatch):
    p = _sleeper(profile)
    browser.PIDFILE_NAME and (profile / browser.PIDFILE_NAME).write_text(str(p.pid))
    monkeypatch.setattr(browser, "_alive", _up)
    assert asyncio.run(browser.ensure_browser()) is None
    assert browser._adopted == p.pid
    browser.shutdown()
    assert p.wait(timeout=10) is not None
    assert browser._adopted is None and not (profile / browser.PIDFILE_NAME).exists()


@pytest.mark.skipif(sys.platform == "win32", reason="process groups")
def test_a_reused_pid_is_never_killed(profile, monkeypatch):
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    try:
        (profile / browser.PIDFILE_NAME).write_text(str(other.pid))  # the pid now belongs to something else
        monkeypatch.setattr(browser, "_alive", _up)
        asyncio.run(browser.ensure_browser())
        assert browser._adopted is None
        browser.shutdown()
        assert other.poll() is None
    finally:
        other.kill()
