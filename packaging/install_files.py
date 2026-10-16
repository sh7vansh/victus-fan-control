#!/usr/bin/python3
"""Stage the application files for Flatpak."""

import argparse
from pathlib import Path
import shutil

from appstream import compose

APP_ID = "io.github.sh7vansh.VictusFanControl"
SOURCE = Path(__file__).resolve().parent.parent


def copy_file(source, destination, mode=0o644):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    destination.chmod(mode)


def install(prefix):
    base = prefix / "share/victus-fan-control"
    for name in ("__init__.py", "__main__.py", "app.py", "hardware.py", "host.py", "authorization.py", "privileged.py"):
        copy_file(SOURCE / "fan_control" / name, base / "fan_control" / name)
    shutil.copytree(SOURCE / "data/icons", base / "data/icons", dirs_exist_ok=True)
    copy_file(SOURCE / "data" / f"{APP_ID}.metainfo.xml", base / "data" / f"{APP_ID}.metainfo.xml")
    launcher = prefix / "bin/fan-control"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text("#!/usr/bin/python3\nfrom pathlib import Path\nimport sys\n"
                        "sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'share/victus-fan-control'))\n"
                        "from fan_control.app import main\nraise SystemExit(main())\n")
    launcher.chmod(0o755)
    desktop = prefix / "share/applications" / f"{APP_ID}.desktop"
    desktop.parent.mkdir(parents=True, exist_ok=True)
    desktop.write_text((SOURCE / "data" / f"{APP_ID}.desktop.in").read_text().replace("@EXEC@", "fan-control"))
    for size in ("scalable", "64x64", "128x128", "256x256", "512x512"):
        extension = "svg" if size == "scalable" else "png"
        copy_file(SOURCE / "data/icons/hicolor" / size / "apps" / f"{APP_ID}.{extension}",
                  prefix / "share/icons/hicolor" / size / "apps" / f"{APP_ID}.{extension}")
    copy_file(SOURCE / "data" / f"{APP_ID}.metainfo.xml", prefix / "share/metainfo" / f"{APP_ID}.metainfo.xml")
    copy_file(SOURCE / "LICENSE", prefix / "share/licenses/victus-fan-control/LICENSE")
    screenshots = SOURCE / "data/screenshots"
    if screenshots.exists():
        shutil.copytree(screenshots, base / "data/screenshots", dirs_exist_ok=True)
    compose(prefix)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", type=Path, required=True)
    args = parser.parse_args()
    install(args.prefix)
