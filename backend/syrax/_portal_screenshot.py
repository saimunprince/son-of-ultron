"""Take one screenshot through the XDG Screenshot portal (GNOME on Wayland, where no ordinary program may read the
screen) and print where the portal saved it, as JSON: {"ok": true, "path": "..."} or {"ok": false, "error": "..."}.

Started by syrax.desktop with the SYSTEM python3, which has PyGObject; SYRAX's venv has no D-Bus library. GNOME may ask
the human once whether SYRAX may take screenshots."""

import json
import random
import sys
from urllib.parse import unquote, urlparse

BUS = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"
TIMEOUT_S = 60


def main():
    # PyGObject belongs to the system python3, never to SYRAX's venv (test_declared_deps): imported here
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    sender = conn.get_unique_name()[1:].replace(".", "_")
    token = f"syraxshot{random.randint(0, 1 << 30)}"
    loop, box = GLib.MainLoop(), {}

    def on_response(_c, _s, _p, _i, _sig, args, _d):
        box["code"], box["results"] = args.unpack()
        loop.quit()

    sub = conn.signal_subscribe(BUS, "org.freedesktop.portal.Request", "Response", f"{PATH}/request/{sender}/{token}", None,
                                Gio.DBusSignalFlags.NO_MATCH_RULE, on_response, None)
    conn.call_sync(BUS, PATH, "org.freedesktop.portal.Screenshot", "Screenshot",
                   GLib.Variant("(sa{sv})", ("", {"handle_token": GLib.Variant("s", token), "interactive": GLib.Variant("b", False)})),
                   None, Gio.DBusCallFlags.NONE, -1, None)
    GLib.timeout_add_seconds(TIMEOUT_S, loop.quit)
    loop.run()
    conn.signal_unsubscribe(sub)
    if "code" not in box:
        raise RuntimeError(f"no answer from the screenshot portal in {TIMEOUT_S} s (was its question answered?)")
    if box["code"] != 0:
        raise RuntimeError(f"the screenshot was refused (code {box['code']})")
    uri = box["results"].get("uri") or ""
    print(json.dumps({"ok": True, "path": unquote(urlparse(uri).path)}))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}))
        sys.exit(0)
