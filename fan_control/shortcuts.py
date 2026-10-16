"""Set up the OMEN launcher on GNOME without replacing user shortcuts."""

import os
import subprocess
import threading

from gi.repository import GLib

from .service import host_command_argv

MEDIA_KEYS = "org.gnome.settings-daemon.plugins.media-keys"
SHORTCUT_SCHEMA = MEDIA_KEYS + ".custom-keybinding"
SHORTCUT_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/omen-fan-control/"
COMMAND = "flatpak run io.github.sh7vansh.victus-fan-control"
LEGACY_COMMAND = "flatpak run io.github.sh7vansh.VictusFanControl"


def gsettings(*args):
    result = subprocess.run(host_command_argv("gsettings", *args),
                            capture_output=True, text=True, check=True, timeout=3)
    return result.stdout.strip()


def read_setting(schema, key):
    return GLib.Variant.parse(None, gsettings("get", schema, key), None, None).unpack()


def write_setting(schema, key, value):
    kind = "as" if isinstance(value, list) else "s"
    gsettings("set", schema, key, GLib.Variant(kind, value).print_(True))


def uses_omen_key(bindings):
    # GDK calls this key Launch2; XF86Launch2 is another common spelling.
    if isinstance(bindings, str):
        bindings = [bindings]
    return any(binding in ("Launch2", "XF86Launch2") for binding in bindings)


def ensure_omen_shortcut():
    """Configure once; existing, edited, or disabled shortcuts remain untouched."""
    schema = SHORTCUT_SCHEMA + ":" + SHORTCUT_PATH
    try:
        # The name also records setup if the user later removes the shortcut
        # from the active list or clears its binding in GNOME Settings.
        if read_setting(schema, "name"):
            if read_setting(schema, "command") == LEGACY_COMMAND:
                write_setting(schema, "command", COMMAND)
            return
        paths = read_setting(MEDIA_KEYS, "custom-keybindings")
        for path in paths:
            if uses_omen_key(read_setting(SHORTCUT_SCHEMA + ":" + path, "binding")):
                return
        for line in gsettings("list-recursively", MEDIA_KEYS).splitlines():
            _schema, key, serialized = line.split(" ", 2)
            if key != "custom-keybindings":
                value = GLib.Variant.parse(None, serialized, None, None).unpack()
                if isinstance(value, (str, list)) and uses_omen_key(value):
                    return
        write_setting(schema, "command", COMMAND)
        write_setting(schema, "binding", "Launch2")
        if SHORTCUT_PATH not in paths:
            write_setting(MEDIA_KEYS, "custom-keybindings", [*paths, SHORTCUT_PATH])
        write_setting(schema, "name", "OMEN — Fan Control")
    except (OSError, subprocess.SubprocessError, GLib.Error):
        # Missing GNOME schemas, locked settings, or host access must not
        # prevent the cooling interface from opening.
        return


def setup_omen_shortcut():
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper().split(":")
    if "GNOME" in desktop:
        threading.Thread(target=ensure_omen_shortcut, daemon=True).start()
