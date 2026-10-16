#!/usr/bin/python3
"""Rasterize the existing SVG identity for desktop and software-store use."""

from pathlib import Path

import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf

ROOT = Path(__file__).resolve().parent.parent
APP_ID = "io.github.sh7vansh.VictusFanControl"
icons = ROOT / "data/icons/hicolor"
for size in (64, 128, 256, 512):
    target = icons / f"{size}x{size}/apps" / f"{APP_ID}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(icons / "scalable/apps" / f"{APP_ID}.svg"), size, size, True)
    pixbuf.savev(str(target), "png", [], [])
    print(target.relative_to(ROOT))
