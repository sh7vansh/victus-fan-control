import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from gi.repository import GLib

from fan_control.hardware import DemoHardware, Hardware
from fan_control.host import HostHardware
from fan_control.power_profiles import (
    GNOME_POWER_PROFILES,
    FIRMWARE_PROFILES,
    is_live_hardware,
    sync_to_desktop,
    subscribe_desktop_changes,
    unsubscribe_desktop_changes,
)


class PowerProfilesSyncTests(unittest.TestCase):
    def test_live_hardware_detection(self):
        self.assertTrue(is_live_hardware(HostHardware()))
        self.assertTrue(is_live_hardware(Hardware(Path("/sys"))))
        self.assertFalse(is_live_hardware(Hardware(Path("/tmp/sys-test"))))
        self.assertFalse(is_live_hardware(DemoHardware()))

    def test_sync_to_desktop_calls_dbus_for_mapped_profiles(self):
        for firmware_profile, gnome_profile in GNOME_POWER_PROFILES.items():
            mock_bus = MagicMock()
            sync_to_desktop(firmware_profile, bus=mock_bus)
            mock_bus.call.assert_called_once()
            args = mock_bus.call.call_args[0]
            self.assertEqual(args[0], "net.hadess.PowerProfiles")
            self.assertEqual(args[1], "/net/hadess/PowerProfiles")
            self.assertEqual(args[2], "org.freedesktop.DBus.Properties")
            self.assertEqual(args[3], "Set")
            variant = args[4]
            unpacked = variant.unpack()
            self.assertEqual(unpacked[0], "net.hadess.PowerProfiles")
            self.assertEqual(unpacked[1], "ActiveProfile")
            self.assertEqual(unpacked[2], gnome_profile)

    def test_sync_to_desktop_skips_unmapped_profiles(self):
        mock_bus = MagicMock()
        sync_to_desktop("cool", bus=mock_bus)
        mock_bus.call.assert_not_called()

        sync_to_desktop("unknown", bus=mock_bus)
        mock_bus.call.assert_not_called()

    def test_sync_to_desktop_handles_missing_bus_or_dbus_errors(self):
        # Should not raise
        sync_to_desktop("balanced", bus=None)

        failing_bus = MagicMock()
        failing_bus.call.side_effect = RuntimeError("D-Bus failure")
        sync_to_desktop("balanced", bus=failing_bus)

    def test_subscribe_and_unsubscribe_desktop_changes(self):
        mock_bus = MagicMock()
        mock_bus.signal_subscribe.return_value = 42

        received = []
        sub_id = subscribe_desktop_changes(lambda p: received.append(p), bus=mock_bus)
        self.assertEqual(sub_id, 42)
        mock_bus.signal_subscribe.assert_called_once()

        # Simulate D-Bus signal invocation
        signal_callback = mock_bus.signal_subscribe.call_args[0][6]
        params = GLib.Variant("(sa{sv}as)", (
            "net.hadess.PowerProfiles",
            {"ActiveProfile": GLib.Variant("s", "power-saver")},
            []
        ))
        signal_callback(mock_bus, "sender", "/net/hadess/PowerProfiles", "org.freedesktop.DBus.Properties", "PropertiesChanged", params)
        self.assertEqual(received, ["quiet"])

        unsubscribe_desktop_changes(sub_id, bus=mock_bus)
        mock_bus.signal_unsubscribe.assert_called_once_with(42)


if __name__ == "__main__":
    unittest.main()
