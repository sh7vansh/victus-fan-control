#!/usr/bin/python3
"""Verify the installer listing through GNOME Software without installing it."""

import argparse
import os
from pathlib import Path
import re
import subprocess

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
if args.installer.suffix == ".flatpakref":
    required = ("description", "icon", "screenshot-00", "screenshot-01", "url{homepage}", "origin")
    for name in required:
        if not field(name):
            raise SystemExit(f"FAIL: GNOME Software is missing {name}.")
    if "local-has-repository" not in field("quirk"):
        raise SystemExit("FAIL: GNOME Software does not recognize the update repository.")
    if not field("size-download") or field("size-download") == "unknown":
        raise SystemExit("FAIL: GNOME Software has no remote download size.")
    print("PASS: icon, description, both screenshots, homepage, MIT license, download size, and update repository recognized.")
else:
    print("PASS: GNOME Software recognizes the MIT license.")
