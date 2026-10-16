#!/usr/bin/python3
"""Inspect the actual .flatpak file, catching missing installer information."""

import argparse
import gzip
from pathlib import Path
import struct
import xml.etree.ElementTree as ET

import gi
gi.require_version("Flatpak", "1.0")
from gi.repository import Flatpak, Gio

APP_ID = "io.github.sh7vansh.victus-fan-control"


def verify(path):
    bundle = Flatpak.BundleRef.new(Gio.File.new_for_path(str(Path(path).resolve())))
    appdata = bundle.get_appstream()
    if not appdata:
        raise ValueError("Bundle is missing embedded AppStream information; the installer would be blank.")
    content = appdata.get_data()
    xml = gzip.decompress(content) if content.startswith(b"\x1f\x8b") else content.rstrip(b"\x00")
    component = ET.fromstring(xml).find("component")
    if component is None:
        raise ValueError("Bundle contains no application component.")
    for key in ("id", "name", "summary", "description", "project_license", "releases/release"):
        if component.find(key) is None:
            raise ValueError(f"Bundle is missing {key}.")
    if component.findtext("id") != APP_ID:
        raise ValueError("Bundle AppStream ID does not match the application.")
    if not (component.findtext("developer/name") or component.findtext("developer_name")):
        raise ValueError("Bundle is missing the developer name.")
    if component.findtext("project_license") != "MIT":
        raise ValueError("Expected MIT project license")
    for kind in ("homepage", "vcs-browser", "bugtracker"):
        if not component.findtext(f"url[@type='{kind}']", "").startswith("https://"):
            raise ValueError(f"Missing public {kind} URL")
    if len(component.findall("screenshots/screenshot/image[@type='source']")) != 2:
        raise ValueError("Expected light and dark screenshots")
    for size in (64, 128):
        icon = bundle.get_icon(size)
        if icon is None:
            raise ValueError(f"Bundle is missing its {size}px installer icon.")
        content = icon.get_data()
        if content[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", content[16:24]) != (size, size):
            raise ValueError(f"Invalid {size}px installer PNG icon.")
    version = component.find("releases/release").get("version")
    print(f"Verified bundle: {component.findtext('name')} {version}; developer, license, description, 64px and 128px icons embedded")
    return component


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    verify(args.bundle)
