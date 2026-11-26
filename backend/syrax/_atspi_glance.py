"""A flash-free fingerprint of what is on the screen, read from the accessibility tree (AT-SPI), for the desktop tool's
"did the screen change after this click" check on GNOME Wayland when the Screenshot portal is off (it flashes).

Started by syrax.desktop with the SYSTEM python3, which has PyGObject; SYRAX's venv has no D-Bus library. Read-only: it
asks the accessibility bus for names, roles, states and child counts and never acts on anything. It prints one JSON
line with only hashes, so no window title or text leaves this process:
  {"ok": true, "parts": {"windows": [hash, complete], "front": [...], "shell": [...]}, "nodes": N}
  {"ok": false, "error": "..."}
- windows: every application's top-level windows: role, title, whether it is the active one (opened, closed, retitled,
  focus moved).
- front: the whole tree of the active window(s): role, name and a few states of each element (a page, a dialog, a tab,
  a checkbox in an app that exposes its tree).
- shell: GNOME Shell's own tree, the SHOWING part, roles and child counts only, never names (its clock changes names
  every minute): popup menus, the overview, shell dialogs, notifications, Wayland surfaces coming and going.
A part cut short by the time budget is marked incomplete, and syrax.desktop then does not compare it."""

import hashlib
import json
import sys
import time

BUDGET_S = 0.7
FRONT_MAX = 1500
SHELL_MAX = 2500
MAX_DEPTH = 40
MAX_KIDS = 300


def main():
    # PyGObject belongs to the system python3, never to SYRAX's venv (test_declared_deps): imported here
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    S = Atspi.StateType
    states = (S.SHOWING, S.FOCUSED, S.SELECTED, S.CHECKED, S.EXPANDED, S.PRESSED, S.SENSITIVE, S.VISIBLE)
    deadline = time.monotonic() + (float(sys.argv[1]) if sys.argv[1:] else BUDGET_S)
    nodes = [0]

    def walk(root, cap, line, descend):
        """sha1 of `line(element)` for the elements under `root`, depth first; (hash, complete)."""
        h, count, stack = hashlib.sha1(), 0, [(root, 0)]
        while stack:
            if time.monotonic() > deadline:
                return h.hexdigest(), False
            o, depth = stack.pop()
            count += 1
            nodes[0] += 1
            try:
                st = o.get_state_set()
                kids = o.get_child_count()
                h.update((line(o, st, kids, depth) + "\n").encode("utf-8", "replace"))
            except Exception:
                h.update(b"?\n")
                continue
            if count >= cap:
                break  # deterministic: the same first `cap` elements every time
            if depth < MAX_DEPTH and (depth == 0 or descend(st)):
                for i in reversed(range(min(kids, MAX_KIDS))):
                    try:
                        c = o.get_child_at_index(i)
                    except Exception:
                        c = None
                    if c is not None:
                        stack.append((c, depth + 1))
        return h.hexdigest(), True

    def front_line(o, st, kids, depth):
        flags = "".join("1" if st.contains(s) else "0" for s in states)
        return f"{depth}|{o.get_role_name()}|{o.get_name() or ''}|{flags}|{kids}"

    def shell_line(o, st, kids, depth):
        return f"{depth}|{o.get_role_name()}|{kids}"

    desktop = Atspi.get_desktop(0)
    windows, fronts, shell = hashlib.sha1(), [], None
    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        if app is None:
            continue
        try:
            name = app.get_name() or ""
            if name == "gnome-shell":
                shell = walk(app, SHELL_MAX, shell_line, lambda st: st.contains(S.SHOWING))
                continue
            for j in range(min(app.get_child_count(), MAX_KIDS)):
                w = app.get_child_at_index(j)
                if w is None:
                    continue
                active = w.get_state_set().contains(S.ACTIVE)
                windows.update(f"{name}|{w.get_role_name()}|{w.get_name() or ''}|{int(active)}\n".encode("utf-8", "replace"))
                if active:
                    fronts.append(w)
        except Exception:
            windows.update(b"?\n")
    parts = {"windows": [windows.hexdigest(), time.monotonic() <= deadline]}
    if fronts:  # none when the window in front does not speak AT-SPI (Waydroid, an X11 app without a bridge)
        front = hashlib.sha1()
        complete = True
        for w in fronts:
            got, done = walk(w, FRONT_MAX, front_line, lambda st: True)
            front.update(got.encode())
            complete = complete and done
        parts["front"] = [front.hexdigest(), complete]
    if shell is not None:
        parts["shell"] = list(shell)
    return {"ok": True, "parts": parts, "nodes": nodes[0]}


if __name__ == "__main__":
    try:
        out = main()
    except Exception as e:  # no accessibility bus, no PyGObject: the caller treats it as "unknown"
        out = {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}
    sys.stdout.write(json.dumps(out) + "\n")  # the answer to syrax.desktop, one JSON line
