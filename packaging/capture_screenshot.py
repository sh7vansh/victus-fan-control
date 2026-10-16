#!/usr/bin/python3
"""Capture the actual preview window in a fixed light or dark appearance."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fan_control.app import FanApplication
from gi.repository import Adw

parser = argparse.ArgumentParser()
parser.add_argument("theme", choices=("light", "dark"))
args = parser.parse_args()
target = Path(__file__).resolve().parent.parent / "data/screenshots" / f"fan-control-{args.theme}.png"
target.parent.mkdir(parents=True, exist_ok=True)
app = FanApplication(demo=True, smoke_test=True, screenshot=target)
app.connect("startup", lambda *_: Adw.StyleManager.get_default().set_color_scheme(
    Adw.ColorScheme.FORCE_LIGHT if args.theme == "light" else Adw.ColorScheme.FORCE_DARK))
app.connect_after("activate", lambda application: application.get_active_window().set_default_size(520, 900))
result = app.run([sys.argv[0]])
if not app.failure and result == 0:
    print(f"Saved {target}")
raise SystemExit(1 if app.failure else result)
