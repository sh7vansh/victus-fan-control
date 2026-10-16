#!/usr/bin/python3
"""Check the license as GNOME Software sees a local Flatpak, not just its XML."""

import argparse
import os
from pathlib import Path
import re
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("bundle", type=Path)
args = parser.parse_args()
environment = os.environ.copy()
environment["LC_ALL"] = "C.UTF-8"
result = subprocess.run(
    ["/usr/libexec/gnome-software-cmd", "--show-results", "--refine-flags=license", "filename-to-app", str(args.bundle.resolve())],
    capture_output=True, text=True, timeout=45, env=environment)
if result.returncode:
    raise SystemExit(result.stderr or result.stdout)
app = result.stdout.split("\tRuntime:", 1)[0]
for line in app.splitlines():
    if re.match(r"^(name|version|license|license-is-free|summary):", line):
        print(line)
license_line = re.search(r"^license:\s*(.+)$", app, re.MULTILINE)
if license_line is None or "MIT" not in license_line.group(1):
    raise SystemExit("FAIL: GNOME Software does not recognize the bundle's MIT license.")
print("PASS: GNOME Software recognizes the MIT license.")
