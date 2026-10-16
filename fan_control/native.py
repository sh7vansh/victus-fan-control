"""Locate the bundled static helper inside and outside Flatpak."""

from configparser import ConfigParser
from pathlib import Path

HELPER_NAME = "victus-fan-control-helper"
FLATPAK_INFO = Path("/.flatpak-info")


def host_helper_path():
    if FLATPAK_INFO.exists():
        info = ConfigParser(interpolation=None)
        info.read_string(FLATPAK_INFO.read_text())
        app_path = Path(info.get("Instance", "app-path", fallback=""))
        if not app_path.is_absolute() or ".." in app_path.parts:
            raise ValueError("Flatpak did not provide an absolute application deployment path.")
        return app_path / "libexec" / HELPER_NAME
    return Path(__file__).resolve().parent.parent / "build/native" / HELPER_NAME


def helper_argv(*args, privileged=False):
    argv = [str(host_helper_path()), *args]
    if privileged:
        argv = ["/usr/bin/pkexec", "--disable-internal-agent", *argv]
    if FLATPAK_INFO.exists():
        prefix = ["/usr/bin/flatpak-spawn", "--host"]
        if privileged:
            prefix.append("--watch-bus")
        argv = [*prefix, *argv]
    return argv
