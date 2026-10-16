#!/usr/bin/python3
"""Build a local Flathub-style candidate and retain official linter results.

Requires Podman, Flatpak, the GNOME runtime, and Go. Does not publish, install
an app, or apply linter exceptions. Host execution still needs external review.
"""

import argparse
import json
from pathlib import Path
import platform
import subprocess
import tempfile

from install_files import APP_ID, SOURCE, install

IMAGE = "ghcr.io/flathub/flatpak-builder-lint:latest"


def check(image=IMAGE):
    output = SOURCE / "build/flathub-lint"
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = SOURCE / f"{APP_ID}.json"
    manifest = json.loads(manifest_path.read_text())
    with tempfile.TemporaryDirectory(prefix="flathub-check-", dir=SOURCE / "build") as directory:
        work = Path(directory)
        stage = work / "app"
        subprocess.run(["flatpak", "build-init", str(stage), APP_ID,
                        manifest["runtime"], manifest["runtime"], manifest["runtime-version"]], check=True)
        install(stage / "files")
        subprocess.run(["flatpak", "build-finish", "--command=fan-control",
                        *manifest["finish-args"], str(stage)], check=True)
        container = ["podman", "run", "--rm", "--security-opt=label=disable",
                     "-v", f"{SOURCE}:/src:ro", "-v", f"{work}:/work:rw", "-w", "/tmp"]
        script = (
            "import sys; from pathlib import Path; import subprocess; "
            "sys.path.insert(0, '/src/packaging'); "
            "from appstream import compose_mirrored; "
            "compose_mirrored(Path('/work/app/files'), 'https://dl.flathub.org/media'); "
            "subprocess.run(['flatpak', 'build-export', '/work/repo', '/work/app', 'stable'], check=True); "
            f"subprocess.run(['ostree', '--repo=/work/repo', 'commit', '--canonical-permissions', '--branch=screenshots/{platform.machine()}', '/work/app/files/share/app-info/media'], check=True)"
        )
        subprocess.run([*container, "--entrypoint=python3", image, "-c", script], check=True)
        summary = {}
        checks = [
            ("appstream", [], "appstream", f"/src/data/{APP_ID}.metainfo.xml"),
            ("manifest", [], "manifest", f"/src/{APP_ID}.json"),
            ("repo", [], "repo", "/work/repo"),
            ("manifest-review", ["--permission-review"], "manifest", f"/src/{APP_ID}.json"),
            ("repo-review", ["--permission-review"], "repo", "/work/repo"),
        ]
        for label, options, kind, path in checks:
            pipeline = ["--env=REPO=https://github.com/flathub/flathub"] if kind == "manifest" else []
            command = [*container, *pipeline, image, *options, kind, path]
            result = subprocess.run(command, capture_output=True, text=True)
            (output / f"{label}.stdout").write_text(result.stdout)
            (output / f"{label}.stderr").write_text(result.stderr)
            summary[label] = {"exit_code": result.returncode, "command": command}
            print(f"{label}: exit {result.returncode}\n{result.stdout}{result.stderr}", flush=True)
        image_info = subprocess.check_output(["podman", "image", "inspect", image], text=True)
        (output / "image.json").write_text(image_info)
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return 1 if any(result["exit_code"] for result in summary.values()) else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=IMAGE, help="Official linter image or pinned image digest")
    args = parser.parse_args()
    raise SystemExit(check(args.image))
