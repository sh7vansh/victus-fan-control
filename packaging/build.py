#!/usr/bin/python3
"""Build Flatpak artifacts and optionally a signed update repository."""

import argparse
import base64
import shutil
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

from install_files import install, SOURCE

sys.path.insert(0, str(SOURCE))
from fan_control import __version__

APP_ID = "io.github.sh7vansh.victus-fan-control"
LEGACY_APP_ID = "io.github.sh7vansh.VictusFanControl"
# Keep the repository identity so existing installations can receive the rebase.
COLLECTION_ID = LEGACY_APP_ID + ".Repository"


def run(*args):
    subprocess.run([str(arg) for arg in args], check=True, cwd=SOURCE)


def flatpak(test=False, signing_key=None, gpg_homedir=None):
    """Build the static helper locally, then stage the app using the Platform.

    The flatpak-builder manifest instead uses the GNOME SDK and Go extension.
    """
    manifest = json.loads((SOURCE / f"{APP_ID}.json").read_text())
    build = SOURCE / "build"
    build.mkdir(exist_ok=True)
    dist = SOURCE / "dist"
    dist.mkdir(exist_ok=True)
    runtime = manifest["runtime"]
    branch = manifest["runtime-version"]
    public = build / "public"
    signing = []
    if signing_key:
        signing = [f"--gpg-sign={signing_key}", f"--gpg-homedir={gpg_homedir.resolve()}"]
        public.mkdir(exist_ok=True)
        key = subprocess.check_output(["gpg", "--homedir", str(gpg_homedir.resolve()),
                                       "--export", signing_key])
        if not key:
            raise SystemExit("Signing public key was not found")
        (public / "signing-key.gpg").write_bytes(key)
    with tempfile.TemporaryDirectory(prefix="flatpak-", dir=build) as directory:
        stage = Path(directory) / "app"
        run("flatpak", "build-init", stage, APP_ID, runtime, runtime, branch)
        install(stage / "files")
        run("flatpak", "build-finish", "--command=fan-control", *manifest["finish-args"], stage)
        if test:
            run("flatpak", "build", stage, "python3", "-c",
                "import sys; sys.path.insert(0, '/app/share/victus-fan-control'); "
                "from fan_control.app import FanApplication; "
                "from fan_control.host import HostHardware; "
                "assert isinstance(FanApplication().hardware, HostHardware); "
                "from fan_control.native import helper_argv; "
                "assert helper_argv('--daemon', privileged=True)[:3] == ['/usr/bin/flatpak-spawn', '--host', '--watch-bus']; "
                "print('Flatpak selects host reads and daemon management path')")
            run("flatpak", "build", *manifest["finish-args"], stage, "/app/bin/fan-control", "--smoke-test")
            run("flatpak", "build", *manifest["finish-args"], stage, "python3", "-c",
                (SOURCE / "packaging/check_sandbox_session.py").read_text())
            run("flatpak", "build", *manifest["finish-args"], stage, "/app/bin/fan-control", "--check-host")
        repo = public / "repo" if signing_key else build / "development-repo"
        collection = [f"--collection-id={COLLECTION_ID}"] if signing_key else []
        run("flatpak", "build-export", *collection, *signing, repo, stage, "stable")
        if signing_key:
            legacy_ref = f"app/{LEGACY_APP_ID}/{platform.machine()}/stable"
            if (repo / "refs/heads" / legacy_ref).is_file():
                run("flatpak", "build-commit-from", *signing, "--no-update-summary",
                    f"--end-of-life-rebase={LEGACY_APP_ID}={APP_ID}",
                    "--end-of-life=Fan Control has moved to its repository-matching application ID.",
                    repo, legacy_ref)
        run("flatpak", "build-update-repo", *signing, "--title=Fan Control",
            "--default-branch=stable", "--homepage=https://sh7vansh.github.io/victus-fan-control/",
            "--generate-static-deltas", repo)
        bundle = dist / f"{APP_ID}-{platform.machine()}.flatpak"
        origin = (["--repo-url=https://sh7vansh.github.io/victus-fan-control/repo/",
                   f"--gpg-keys={public / 'signing-key.gpg'}"] if signing_key else [])
        run("flatpak", "build-bundle", *origin, repo, bundle, APP_ID, "stable",
            "--runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo")
        if signing_key:
            make_site(public, base64.b64encode(key).decode("ascii"))
            for name in ("fan-control.flatpakref", "fan-control.flatpakrepo", "signing-key.gpg"):
                shutil.copyfile(public / name, dist / name)
        run("/usr/bin/python3", SOURCE / "packaging/verify_bundle.py", bundle)
        print(f"Created {bundle}")


def make_site(public, public_key):
    homepage = "https://sh7vansh.github.io/victus-fan-control/"
    common = (f"Title=Fan Control\nComment=Cooling controls for HP Victus and OMEN\n"
              f"Description=Thermal profiles, maximum fan mode, and live fan speeds.\n"
              f"Url={homepage}repo/\nHomepage={homepage}\n"
              f"Icon={homepage}icon.png\nGPGKey={public_key}\n")
    (public / "fan-control.flatpakrepo").write_text("[Flatpak Repo]\n" + common)
    (public / "fan-control.flatpakref").write_text(
        f"[Flatpak Ref]\nName={APP_ID}\nBranch=stable\nIsRuntime=false\n"
        "SuggestRemoteName=victus-fan-control\n"
        "RuntimeRepo=https://dl.flathub.org/repo/flathub.flatpakrepo\n" + common)
    (public / ".nojekyll").touch()
    template = (SOURCE / "packaging/site/index.html").read_text()
    (public / "index.html").write_text(template.replace("@VERSION@", __version__))
    shutil.copyfile(SOURCE / f"data/icons/hicolor/128x128/apps/{APP_ID}.png", public / "icon.png")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("format", choices=("flatpak",))
    parser.add_argument("--test", action="store_true", help="Smoke-test the UI inside Flatpak before export (requires a display)")
    parser.add_argument("--signing-key", help="GPG fingerprint for a public release")
    parser.add_argument("--gpg-homedir", type=Path, help="Dedicated signing key directory outside the checkout")
    args = parser.parse_args()
    if bool(args.signing_key) != bool(args.gpg_homedir):
        parser.error("--signing-key and --gpg-homedir must be supplied together")
    flatpak(args.test, args.signing_key, args.gpg_homedir)
