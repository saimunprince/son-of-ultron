"""Live 2026-10-25 (Prince): "not web i have alredy installed whatsapp application in my system." launch_app found no
Start Menu shortcut, list_apps had none either, and SYRAX answered "WhatsApp is not installed as a desktop
application on this system"; it was, as a Microsoft Store app (5319275A.WhatsAppDesktop). On Windows the app list
now also holds the Start apps that are not a shortcut file (Get-StartApps), launched through shell:AppsFolder; an
alias that finds nothing ("whatsapp" is "whatsapp web") falls back to the words as said. PowerShell, the Start Menu
and the launcher are faked: nothing starts on the test machine."""

import asyncio
import json
import subprocess

import pytest

from syrax import desktop as D

WHATSAPP = "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"
ROWS = [
    {"Name": "WhatsApp", "AppID": WHATSAPP},
    {"Name": "Telegram", "AppID": "Telegram.TelegramDesktop"},
    {"Name": "Uninstall Telegram", "AppID": r"C:\Users\x\AppData\Roaming\Telegram Desktop\unins000.exe"},
    {"Name": "Windows PowerShell", "AppID": r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"},
    {"Name": "Readme", "AppID": "readme.txt"},
    {"Name": "Netflix", "AppID": "4DF9E0F8.Netflix_mcm4njqhnhss8!Netflix.App"},
]


@pytest.fixture
def start_apps(monkeypatch):
    calls = []
    answer = {"out": json.dumps(ROWS).encode()}

    def run(args, capture_output=True, timeout=20):
        calls.append(args)
        if answer.get("fail"):
            raise subprocess.TimeoutExpired(args, timeout)
        return subprocess.CompletedProcess(args, 0, stdout=answer["out"], stderr=b"")

    monkeypatch.setattr(D.subprocess, "run", run)
    monkeypatch.setattr(D, "_start_apps", {"at": float("-inf"), "apps": []})
    return calls, answer


def test_store_apps_are_read_and_paths_are_left_to_the_shortcut_scan(start_apps):
    apps = D._win_start_apps(now=1000.0)
    assert [(a["name"], a["id"]) for a in apps] == [
        ("WhatsApp", D.APPS_FOLDER + WHATSAPP), ("Telegram", D.APPS_FOLDER + "Telegram.TelegramDesktop"),
        ("Netflix", D.APPS_FOLDER + "4DF9E0F8.Netflix_mcm4njqhnhss8!Netflix.App")]
    assert "Get-StartApps" in start_apps[0][0][-1]


def test_the_list_is_read_once_in_a_while(start_apps):
    calls, _ = start_apps
    D._win_start_apps(now=1000.0)
    D._win_start_apps(now=1000.0 + D.START_APPS_TTL_S - 1)
    assert len(calls) == 1
    D._win_start_apps(now=1000.0 + D.START_APPS_TTL_S + 1)
    assert len(calls) == 2


def test_one_app_and_no_answer_are_both_handled(start_apps):
    _, answer = start_apps
    answer["out"] = json.dumps({"Name": "WhatsApp", "AppID": WHATSAPP}).encode()  # ConvertTo-Json of a single row
    assert [a["name"] for a in D._win_start_apps(now=1.0)] == ["WhatsApp"]
    answer["fail"] = True
    assert D._win_start_apps(now=1.0 + D.START_APPS_TTL_S + 1) == []


def test_shortcuts_come_first_and_a_store_app_of_the_same_name_is_not_listed_twice(start_apps, monkeypatch, tmp_path):
    menu = tmp_path / "Programs" / "Telegram Desktop"
    menu.mkdir(parents=True)
    (menu / "Telegram.lnk").write_bytes(b"")
    monkeypatch.setattr(D, "WIN_START_MENUS", [str(tmp_path / "Programs")])
    names = [(a["name"], a["id"].startswith(D.APPS_FOLDER)) for a in D._win_installed_apps()]
    assert names == [("Telegram", False), ("WhatsApp", True), ("Netflix", True)]


def test_whatsapp_is_the_store_app_where_there_is_no_web_app():
    store = [{"id": D.APPS_FOLDER + WHATSAPP, "name": "WhatsApp", "generic": "", "keywords": "", "exec": ""}]
    assert D.match_app("whatsapp", store)["name"] == "WhatsApp"
    web = store + [{"id": "whatsapp-web.desktop", "name": "WhatsApp Web", "generic": "", "keywords": "", "exec": ""}]
    assert D.match_app("whatsapp", web)["id"] == "whatsapp-web.desktop"  # the alias still wins where it exists
    assert D.match_app("photoshop", store) is None


def test_a_store_app_is_launched_through_the_shell(monkeypatch):
    ran = []

    async def run(*args, **kw):
        ran.append((args, kw.get("detach")))
        return 0, "", ""

    monkeypatch.setattr(D, "WINDOWS", True)
    monkeypatch.setattr(D, "_run", run)
    monkeypatch.setattr(D, "installed_apps", lambda: [{"id": D.APPS_FOLDER + WHATSAPP, "name": "WhatsApp", "generic": "",
                                                       "keywords": "", "exec": ""}])
    out = asyncio.run(D.DesktopControl().execute(action="launch_app", target="whatsapp"))
    assert out.output == "Launched WhatsApp." and ran == [(("explorer.exe", D.APPS_FOLDER + WHATSAPP), True)]
