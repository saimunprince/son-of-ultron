"""Live 2026-10-26 15:01: "Is the WhatsApp desktop app installed?" was answered right (5319275A.WhatsAppDesktop) but in
six steps: two file searches (one cut by its time budget), two python scripts, then Get-AppxPackage. list_apps holds
Microsoft Store apps since b1c2ad1 and would have answered in one; the desktop tool's description now says so."""

from syrax.desktop import DesktopControl


def test_the_description_names_list_apps_for_whether_an_app_is_installed():
    d = DesktopControl()
    assert "Whether an app is installed: list_apps with its name" in d.description
    assert "Microsoft Store apps such as WhatsApp included), never a file search" in d.description
    assert "launch_app/list_apps: app name (Store apps included)." in d.parameters["properties"]["target"]["description"]
