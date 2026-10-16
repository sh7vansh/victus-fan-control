#!/usr/bin/python3
"""Capture a live app window using read-only hardware access."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fan_control.app import FanApplication
from gi.repository import Adw, Gio, GLib, Gtk

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("theme", choices=("light", "dark"))
args = parser.parse_args()
target = Path(__file__).resolve().parent.parent / "data/screenshots" / f"fan-control-{args.theme}.png"
target.parent.mkdir(parents=True, exist_ok=True)
# No smoke test: that exercises controls. This instance only reads real sensors.
app = FanApplication(screenshot=target)
app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
app.connect("startup", lambda *_: Adw.StyleManager.get_default().set_color_scheme(
    Adw.ColorScheme.FORCE_LIGHT if args.theme == "light" else Adw.ColorScheme.FORCE_DARK))


def capture():
    try:
        window = app.get_active_window()
        assert not window.busy, "A setting change is pending"
        snapshot = Gtk.Snapshot.new()
        app.capture_paintable.snapshot(snapshot, window.get_width(), window.get_height())
        node = snapshot.to_node()
        if node is None:
            raise RuntimeError("The window has not rendered")
        texture = window.get_renderer().render_texture(node, None)
        if not texture.save_to_png(str(target)):
            raise RuntimeError("Screenshot could not be saved")
        print(f"Saved {target} ({window.get_width()} × {window.get_height()}); live readings, no settings changed")
        window.close()
    except Exception as error:
        print(f"Capture failed: {error}", file=sys.stderr)
        app.failure = True
        app.quit()
    return GLib.SOURCE_REMOVE


def activated(application):
    application.get_active_window().set_default_size(520, 820)
    GLib.timeout_add(1400, capture)


app.connect_after("activate", activated)
result = app.run([sys.argv[0]])
raise SystemExit(1 if app.failure else result)
