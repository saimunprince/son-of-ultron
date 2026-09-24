import asyncio
import os

os.environ.setdefault("OPENMANUS_DISABLE_BROWSER_USE", "1")

from syrax.desktop import DesktopControl, _looks_like_url, match_app  # noqa: E402

APPS = [
    {"id": "google-chrome.desktop", "name": "Google Chrome", "generic": "Web Browser", "keywords": "", "exec": "/usr/bin/google-chrome-stable"},
    {"id": "waydroid.com.android.chrome.desktop", "name": "Chrome", "generic": "", "keywords": "", "exec": "waydroid"},
    {"id": "code.desktop", "name": "Visual Studio Code", "generic": "Text Editor", "keywords": "vscode;", "exec": "/usr/share/code/code"},
    {"id": "antigravity.desktop", "name": "Antigravity", "generic": "Text Editor", "keywords": "vscode;", "exec": "antigravity"},
    {"id": "org.gnome.Nautilus.desktop", "name": "Files", "generic": "", "keywords": "folder;manager;explore;", "exec": "nautilus"},
    {"id": "firefox_firefox.desktop", "name": "Firefox", "generic": "Web Browser", "keywords": "Internet;WWW;Browser;", "exec": "firefox"},
]


def test_app_matching_prefers_real_desktop_apps():
    pick = lambda q: (match_app(q, APPS) or {}).get("id")
    assert pick("chrome") == "google-chrome.desktop"
    assert pick("android chrome") == "waydroid.com.android.chrome.desktop"
    assert pick("vs code") == "code.desktop"
    assert pick("VSCode") == "code.desktop"
    assert pick("antigravity") == "antigravity.desktop"
    assert pick("file manager") == "org.gnome.Nautilus.desktop"
    assert pick("firefox") == "firefox_firefox.desktop"
    assert pick("photoshop") is None


def test_url_detection():
    assert _looks_like_url("youtube.com") and _looks_like_url("https://x.io/a") and _looks_like_url("www.google.com")
    assert not _looks_like_url("my notes") and not _looks_like_url("/home/prince")


def test_unknown_action_and_missing_args_are_errors():
    d = DesktopControl()
    run = lambda c: asyncio.new_event_loop().run_until_complete(c)
    assert run(d.execute(action="shutdown")).error
    assert run(d.execute(action="open")).error
    assert run(d.execute(action="notify")).error
    assert run(d.execute(action="volume", value="loud")).error


def test_system_info_and_find_files(tmp_path):
    (tmp_path / "project").mkdir()
    (tmp_path / "project" / "Report-final.pdf").write_text("x")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "report.js").write_text("x")
    d = DesktopControl()
    run = lambda c: asyncio.new_event_loop().run_until_complete(c)
    info = run(d.execute(action="system_info")).output
    assert "RAM" in info and "Disk" in info
    found = run(d.execute(action="find_files", target="report", folder=str(tmp_path))).output
    assert "Report-final.pdf" in found and "node_modules" not in found
