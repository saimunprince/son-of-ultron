"""The owner (2026-11-05): SYRAX runs right on any Linux, any Windows and other systems, and knows its own system.
The host profile says which desktop actions work on this system, and the agent is told the ones that do not."""

from syrax import hostprofile as H

ALL = {t: True for t in H.TOOLS}
NONE = {t: False for t in H.TOOLS}


def test_gnome_wayland_has_hands_through_the_portal_but_no_window_control():
    a = H.actions("Linux", "GNOME", "wayland", ALL, True, True)
    assert a["type_text"] == a["click"] == a["screenshot"] == a["clipboard"] == "yes"
    assert a["window"].startswith("no") and "Wayland" in a["window"]
    assert a["click_text"].startswith("no") and a["display_off"].startswith("no")


def test_kde_on_x11_without_helpers_says_what_is_missing():
    a = H.actions("Linux", "KDE", "x11", NONE, False, False)
    assert a["type_text"].startswith("no: needs GNOME")
    assert "wpctl nor amixer" in a["volume"] and "playerctl" in a["media"] and "xsel on X11" in a["clipboard"]
    assert a["camera"].startswith("no") and a["phone"].startswith("no") and a["view_video"].startswith("no")
    assert "Wayland" not in a["window"]


def test_windows_can_do_every_desktop_action():
    a = H.actions("Windows", "Windows shell", "windows", ALL, False, True)
    assert all(v == "yes" for v in a.values()), a


def test_macos_has_no_hands():
    a = H.actions("macOS", "Aqua", "quartz", ALL, False, True)
    assert a["screenshot"] == "yes" and a["click"].startswith("no") and a["window"].startswith("no")


def test_the_summary_names_the_system_and_what_not_to_try():
    p = {"os": "Linux", "name": "Fedora Linux 43", "arch": "x86_64", "desktop": "KDE", "display": "x11",
         "actions": H.actions("Linux", "KDE", "x11", NONE, False, True)}
    line = H.summary(p)
    assert line.startswith("THIS COMPUTER: Fedora Linux 43, KDE on X11 (x86_64).")
    assert "do not try them" in line and "window" in line and "type_text" in line
    win = {"os": "Windows", "name": "Windows 11 (build 10.0.26100)", "arch": "AMD64", "desktop": "Windows shell",
           "display": "windows", "actions": H.actions("Windows", "", "windows", ALL, False, True)}
    assert H.summary(win) == "THIS COMPUTER: Windows 11 (build 10.0.26100) (AMD64)."


def test_this_computer_is_read_and_self_inspect_shows_it():
    p = H.profile(refresh=True)
    assert p["os"] in ("Linux", "Windows", "macOS") and p["name"] and set(p["actions"]) >= {"window", "screenshot", "phone"}
    from syrax.journal import Journal
    from syrax.selfmodel import SelfModel

    import tempfile, pathlib

    with tempfile.TemporaryDirectory() as d:
        rt = SelfModel(Journal(pathlib.Path(d) / "j.db")).snapshot("runtime")
    system = rt.get("system") or rt.get("runtime", {}).get("system")
    assert system and system["os"] == p["os"] and "tools_found" in system
