"""Desktop power-profile integration."""

from pathlib import Path
from gi.repository import Gio, GLib

from .hardware import Hardware
from .host import HostHardware


GNOME_POWER_PROFILES = {
    "quiet": "power-saver",
    "balanced": "balanced",
    "performance": "performance",
}

FIRMWARE_PROFILES = {
    "power-saver": "quiet",
    "balanced": "balanced",
    "performance": "performance",
}


def is_live_hardware(hardware) -> bool:
    if isinstance(hardware, HostHardware):
        return True
    if isinstance(hardware, Hardware) and hardware.root == Path("/sys"):
        return True
    return False


def get_system_bus() -> Gio.DBusConnection | None:
    try:
        return Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    except Exception:
        return None


def sync_to_desktop(profile: str, bus: Gio.DBusConnection | None = None) -> None:
    gnome_profile = GNOME_POWER_PROFILES.get(profile)
    if not gnome_profile:
        return

    bus = bus or get_system_bus()
    if bus is None:
        return

    def on_called(conn, res, *_user_data):
        try:
            conn.call_finish(res)
        except Exception:
            pass

    try:
        bus.call(
            "net.hadess.PowerProfiles",
            "/net/hadess/PowerProfiles",
            "org.freedesktop.DBus.Properties",
            "Set",
            GLib.Variant("(ssv)", (
                "net.hadess.PowerProfiles",
                "ActiveProfile",
                GLib.Variant("s", gnome_profile),
            )),
            None,
            Gio.DBusCallFlags.NONE,
            -1,
            None,
            on_called,
        )
    except Exception:
        pass


def subscribe_desktop_changes(callback, bus: Gio.DBusConnection | None = None) -> int | None:
    bus = bus or get_system_bus()
    if bus is None:
        return None

    def on_signal(conn, sender, path, iface, signal, params, *user_data):
        try:
            iface_name, changed, _ = params.unpack()
            if iface_name == "net.hadess.PowerProfiles" and "ActiveProfile" in changed:
                gnome_val = changed["ActiveProfile"]
                firmware_val = FIRMWARE_PROFILES.get(gnome_val)
                callback(firmware_val)
        except Exception:
            pass

    try:
        return bus.signal_subscribe(
            "net.hadess.PowerProfiles",
            "org.freedesktop.DBus.Properties",
            "PropertiesChanged",
            "/net/hadess/PowerProfiles",
            None,
            Gio.DBusSignalFlags.NONE,
            on_signal,
            None,
        )
    except Exception:
        return None


def unsubscribe_desktop_changes(sub_id: int | None, bus: Gio.DBusConnection | None = None) -> None:
    if sub_id is None:
        return
    bus = bus or get_system_bus()
    if bus is None:
        return
    try:
        bus.signal_unsubscribe(sub_id)
    except Exception:
        pass
