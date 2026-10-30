"""Run a list of keyboard and pointer actions through the XDG RemoteDesktop portal (GNOME on Wayland), then exit.

Started by syrax.linuxinput with the SYSTEM python3, which has PyGObject (gi); SYRAX's own venv has no D-Bus library
and this keeps it free of a new dependency. Input on stdin, one JSON object:
    {"token": "<restore token or empty>", "actions": [["key", keysym, pressed], ["move", dx, dy], ["button", code, pressed],
                                                      ["sleep", seconds]]}
Output on stdout, one JSON object: {"ok": true, "token": "<restore token>"} or {"ok": false, "error": "..."}.
The first run shows GNOME's "allow remote interaction" dialog; with persist_mode 2 the portal returns a token that
lets later runs start without asking. Stdlib and gi only."""

import json
import random
import sys
import time

BUS = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"
IFACE = "org.freedesktop.portal.RemoteDesktop"
KEYBOARD, POINTER = 1, 2
TIMEOUT_S = 90


def main():
    # PyGObject belongs to the system python3 this helper runs under, never to SYRAX's venv: imported here, so the
    # venv's declared-dependency check (test_declared_deps) rightly sees no module-level import of it
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    req = json.loads(sys.stdin.read() or "{}")
    conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    sender = conn.get_unique_name()[1:].replace(".", "_")
    loop = GLib.MainLoop()

    def call(method, params, expect_response=True):
        token = f"syrax{random.randint(0, 1 << 30)}"
        if expect_response:
            params = params(token)
        box = {}
        if expect_response:
            path = f"{PATH}/request/{sender}/{token}"

            def on_response(_c, _s, _p, _i, _sig, args, _d):
                box["code"], box["results"] = args.unpack()
                loop.quit()

            sub = conn.signal_subscribe(BUS, "org.freedesktop.portal.Request", "Response", path, None,
                                        Gio.DBusSignalFlags.NO_MATCH_RULE, on_response, None)
        conn.call_sync(BUS, PATH, IFACE, method, params, None, Gio.DBusCallFlags.NONE, -1, None)
        if not expect_response:
            return None
        GLib.timeout_add_seconds(TIMEOUT_S, loop.quit)
        loop.run()
        conn.signal_unsubscribe(sub)
        if "code" not in box:
            raise RuntimeError(f"{method}: no answer from the portal in {TIMEOUT_S} s (was the permission dialog answered?)")
        if box["code"] != 0:
            raise RuntimeError(f"{method}: refused by the portal or the human (code {box['code']})")
        return box["results"]

    created = call("CreateSession", lambda t: GLib.Variant("(a{sv})", ({
        "handle_token": GLib.Variant("s", t), "session_handle_token": GLib.Variant("s", t + "s")},)))
    session = created["session_handle"]
    opts = {"handle_token": None, "types": GLib.Variant("u", KEYBOARD | POINTER), "persist_mode": GLib.Variant("u", 2)}
    if req.get("token"):
        opts["restore_token"] = GLib.Variant("s", req["token"])

    def select(t):
        o = dict(opts, handle_token=GLib.Variant("s", t))
        return GLib.Variant("(oa{sv})", (session, o))

    call("SelectDevices", select)
    started = call("Start", lambda t: GLib.Variant("(osa{sv})", (session, "", {"handle_token": GLib.Variant("s", t)})))
    token = started.get("restore_token") or req.get("token") or ""
    empty = {}
    for a in req.get("actions") or []:
        kind = a[0]
        if kind == "key":
            call("NotifyKeyboardKeysym", GLib.Variant("(oa{sv}iu)", (session, empty, int(a[1]), 1 if a[2] else 0)), False)
        elif kind == "move":
            call("NotifyPointerMotion", GLib.Variant("(oa{sv}dd)", (session, empty, float(a[1]), float(a[2]))), False)
        elif kind == "button":
            call("NotifyPointerButton", GLib.Variant("(oa{sv}iu)", (session, empty, int(a[1]), 1 if a[2] else 0)), False)
        elif kind == "sleep":
            time.sleep(min(float(a[1]), 1.0))
    conn.call_sync(BUS, session, "org.freedesktop.portal.Session", "Close", None, None, Gio.DBusCallFlags.NONE, -1, None)
    print(json.dumps({"ok": True, "token": token}))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # one line for the caller; never a traceback with session details
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}))
