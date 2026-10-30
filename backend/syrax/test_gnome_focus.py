"""EVOLUTION_PLAN wave 3 (directions 226 application-state awareness, 227 action verification): on GNOME (Wayland)
the desktop tool could not tell which window was in front (GetWindows is "not allowed", Eval is off), so keys could go
to SYRAX's own chat unchecked and "the keys went to X" was never said. SYRAX's own small shell extension exports the
focused window's title and app class; gdbus reads it. Without the extension, nothing changes (None)."""

import json

from syrax import desktop as D
from syrax import gnomefocus


def gdbus(obj):
    """What gdbus prints for the extension's answer: ASCII JSON (\\uXXXX beyond ASCII), with \\ and ' escaped."""
    text = json.dumps(obj, ensure_ascii=True).replace("\\", "\\\\").replace("'", "\\'")
    return lambda: "('" + text + "',)\n"


def test_the_focused_window_is_read_with_quotes_and_non_ascii():
    title = "Prince's notes \u2014 \u0986\u099c \u2013 Text Editor"
    w = gnomefocus.read(gdbus({"title": title, "wm_class": "org.gnome.TextEditor"}))
    assert w == {"title": title, "wm_class": "org.gnome.TextEditor"}
    assert gnomefocus.read(lambda: "('null',)") == {}
    assert gnomefocus.read(lambda: "Error: GDBus.Error:org.freedesktop.DBus.Error.ServiceUnknown") is None


def test_front_read_uses_it_off_windows_and_spots_syrax_s_own_window(monkeypatch):
    monkeypatch.setattr(D, "WINDOWS", False)
    monkeypatch.setattr(D, "MACOS", False)
    monkeypatch.setattr(gnomefocus, "read", lambda runner=None: {"title": "SYRAX - Google Chrome", "wm_class": "Google-chrome"})
    words, own = D.front_read()
    assert words == "'SYRAX - Google Chrome' (Google-chrome)" and own == "SYRAX - Google Chrome"
    monkeypatch.setattr(gnomefocus, "read", lambda runner=None: {"title": "Untitled 1 - Text Editor", "wm_class": "org.gnome.TextEditor"})
    assert D.front_read() == ("'Untitled 1 - Text Editor' (org.gnome.TextEditor)", "")
    monkeypatch.setattr(gnomefocus, "read", lambda runner=None: None)
    assert D.front_read() == (None, "")  # no extension: as before
