#!/usr/bin/python3
"""Verify the installer listing through GNOME Software without installing it."""

import argparse
from hashlib import sha256
import os
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("installer", type=Path, help="Published .flatpakref, or .flatpak for bundle diagnostics")
args = parser.parse_args()
environment = os.environ.copy()
environment["LC_ALL"] = "C.UTF-8"
try:
    result = subprocess.run(
        ["/usr/libexec/gnome-software-cmd", "--show-results", "--refine-flags=all",
         "filename-to-app", str(args.installer.resolve())],
        capture_output=True, text=True, timeout=90, env=environment)
except subprocess.TimeoutExpired:
    raise SystemExit("FAIL: GNOME Software timed out resolving the repository; check connectivity and retry.")
if result.returncode:
    raise SystemExit(result.stderr or result.stdout)
app = result.stdout.split("\tRuntime:", 1)[0]

def field(name):
    match = re.search(r"^" + re.escape(name) + r":\s*(.+)$", app, re.MULTILINE)
    return match.group(1).strip() if match else ""

for name in ("name", "version", "license", "origin", "size-download"):
    print(f"{name}: {field(name) or '(missing)'}")
if field("license") != "MIT":
    raise SystemExit("FAIL: GNOME Software does not recognize the MIT license. Use the repository-backed .flatpakref.")
# Check the actual cached image data, not merely the presence of an icon field.
source_icons = Path(__file__).resolve().parent.parent / "data/icons/hicolor"
expected_icons = {sha256(path.read_bytes()).digest() for path in source_icons.glob("*/apps/*.png")}
icon_paths = [Path(value.strip()) for value in re.findall(r"^icon:\s*(/.+)$", app, re.MULTILINE)]
if not any(path.is_file() and sha256(path.read_bytes()).digest() in expected_icons for path in icon_paths):
    raise SystemExit("FAIL: GNOME Software does not resolve a cached custom fan icon.")
print("PASS: GNOME Software's cached icon matches the custom fan artwork.")
if args.installer.suffix == ".flatpakref":
    required = ("description", "icon", "screenshot-00", "screenshot-01", "url{homepage}", "origin")
    for name in required:
        if not field(name):
            raise SystemExit(f"FAIL: GNOME Software is missing {name}.")
    metadata = ET.parse(source_icons.parent.parent / "io.github.sh7vansh.VictusFanControl.metainfo.xml").getroot()
    for index, image in enumerate(metadata.findall("screenshots/screenshot/image")):
        if image.text not in field(f"screenshot-{index:02d}"):
            raise SystemExit("FAIL: GNOME Software still resolves an older screenshot URL. Refresh the app's repository catalog.")
    installed = field("state") == "installed"
    if not installed and "local-has-repository" not in field("quirk"):
        raise SystemExit("FAIL: GNOME Software does not recognize the update repository.")
    if not installed and (not field("size-download") or field("size-download") == "unknown"):
        raise SystemExit("FAIL: GNOME Software has no remote download size.")
    print("PASS: icon, description, both screenshots, homepage, MIT license, and update repository recognized.")
    if not installed:
        print("PASS: remote download size recognized.")
else:
    print("PASS: GNOME Software recognizes the MIT license.")
