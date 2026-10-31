"""Live 2026-10-31 (objective #35): youtube_open calls webbrowser.open and declared risk EXTERNAL_READ, and its
source read as READ_ONLY. So SYRAX's own autonomous work opened a browser window on the human's screen (own work
never acts on the host at SYSTEM), and the claim check, seeing no desktop-class tool, called the window it had opened
unproven. Code that acts on the host's screen or input is SYSTEM, whatever the skill declares."""

from syrax import claims, permissions

OPENS = '''import webbrowser
def go(url):
    webbrowser.open(url)
'''


def test_code_that_opens_a_window_or_types_is_system():
    assert permissions.level_of_source(OPENS)[0] == permissions.SYSTEM
    assert permissions.level_of_source("import os\nos.startfile('a.mp3')\n")[0] == permissions.SYSTEM
    assert permissions.level_of_source("import pyautogui\npyautogui.write('hi')\n")[0] == permissions.SYSTEM
    assert permissions.level_of_source("import urllib.request\nurllib.request.urlopen('https://x.org')\n")[0] == permissions.EXTERNAL_READ


def test_a_system_skill_stands_for_the_desktop_outcome():
    assert "desktop" in claims.classes_of("youtube_open", permissions.level_of_source(OPENS)[0], {"query": "lofi"})
