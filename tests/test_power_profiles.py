import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from gi.repository import GLib

from fan_control.hardware import DemoHardware, Hardware
from fan_control.host import HostHardware
from fan_control.power_profiles import (
    GNOME_POWER_PROFILES,
    is_live_hardware,
    sync_to_desktop,
    subscribe_desktop_changes,
    unsubscribe_desktop_changes,
)


class PowerProfilesSyncTests(unittest.TestCase):
    def window(self):
        from fan_control.app import FanWindow
        window = SimpleNamespace(
            desktop_refresh_source=0, pending_desktop_profile=None,
            desktop_write_profile=None, closing=False, busy=False,
            hardware=DemoHardware(), refresh=MagicMock(return_value=GLib.SOURCE_CONTINUE),
            begin_write=MagicMock(), fail=MagicMock(), update_authorization=MagicMock(),
            spinner=MagicMock(), toast_overlay=MagicMock(),
        )
        window._on_desktop_profile_change = lambda profile: FanWindow._on_desktop_profile_change(window, profile)
        window._apply_desktop_profile = lambda poll=True: FanWindow._apply_desktop_profile(window, poll)
        return window

    def test_desktop_refresh_runs_once_even_when_refresh_returns_continue(self):
        from fan_control.app import FanWindow
        window = self.window()
        with patch("fan_control.app.GLib.timeout_add", return_value=42) as schedule:
            FanWindow._on_desktop_profile_change(window, "balanced")
        callback = schedule.call_args.args[1]
        self.assertEqual(callback(), GLib.SOURCE_REMOVE)
        window.refresh.assert_called_once_with()
        self.assertEqual(window.desktop_refresh_source, 0)

    def test_desktop_changes_share_one_pending_refresh(self):
        from fan_control.app import FanWindow
        window = self.window()
        with patch("fan_control.app.GLib.timeout_add", return_value=42) as schedule:
            FanWindow._on_desktop_profile_change(window, "quiet")
            FanWindow._on_desktop_profile_change(window, "balanced")
            schedule.assert_called_once()
            schedule.call_args.args[1]()
            window.begin_write.assert_not_called()
            FanWindow._on_desktop_profile_change(window, "performance")
            self.assertEqual(schedule.call_count, 2)

    def test_close_cancels_pending_desktop_refresh(self):
        from fan_control.app import FanWindow
        window = SimpleNamespace(busy=False, poll_source=41, desktop_refresh_source=42,
                                 desktop_sync_id=None, authorization=None)
        with patch("fan_control.app.GLib.source_remove") as remove:
            self.assertFalse(FanWindow.on_close(window, None))
        self.assertEqual([call.args[0] for call in remove.call_args_list], [41, 42])
        self.assertEqual(window.desktop_refresh_source, 0)

    def test_desktop_change_applies_firmware_without_echo(self):
        window = self.window()
        window.pending_desktop_profile = "performance"
        window._apply_desktop_profile()
        request = window.begin_write.call_args.args[0]
        self.assertEqual(request.value, "performance")
        self.assertFalse(window.begin_write.call_args.kwargs["sync_desktop"])

    def test_desktop_change_waits_until_current_write_finishes(self):
        from fan_control.app import FanWindow
        window = self.window()
        window.busy = True
        window.hardware.profile = "cool"
        window.pending_desktop_profile = "quiet"
        window._apply_desktop_profile()
        window.begin_write.assert_not_called()
        self.assertEqual(window.pending_desktop_profile, "quiet")
        request = window.hardware.profile_request("cool")
        with patch("fan_control.app.GLib.timeout_add", return_value=42) as schedule:
            FanWindow.complete_write(window, request, "Cool applied", sync_desktop=False)
            self.assertEqual(schedule.call_args.args[1](), GLib.SOURCE_REMOVE)
        self.assertEqual(window.begin_write.call_args.args[0].value, "quiet")

    def test_own_desktop_signal_does_not_replace_queued_external_change(self):
        window = self.window()
        window.desktop_write_profile = "balanced"
        window.pending_desktop_profile = "quiet"
        window._on_desktop_profile_change("balanced")
        self.assertEqual(window.pending_desktop_profile, "quiet")

    def test_unsupported_desktop_profile_reports_mismatch(self):
        window = self.window()
        window.pending_desktop_profile = "quiet"
        window.hardware.profile_request = MagicMock(side_effect=ValueError("Unsupported profile"))
        window._apply_desktop_profile()
        window.begin_write.assert_not_called()
        self.assertIn("Unsupported profile", window.fail.call_args.args[0])

    def test_host_poll_callback_does_not_apply_after_close(self):
        window = self.window()
        window.hardware = HostHardware()
        window.hardware.poll = MagicMock()
        window.pending_desktop_profile = "performance"
        window._apply_desktop_profile()
        callback = window.hardware.poll.call_args.args[0]
        window.closing = True
        callback()
        window.begin_write.assert_not_called()

    def test_outgoing_sync_waits_for_completion_and_rechecks_firmware(self):
        from fan_control.app import FanWindow
        window = self.window()
        window.busy = True
        request = window.hardware.profile_request("balanced")
        with patch("fan_control.app.is_live_hardware", return_value=True), \
             patch("fan_control.app.sync_to_desktop") as sync:
            FanWindow.complete_write(window, request, "Balanced applied")
        self.assertTrue(window.busy)
        window.hardware.profile = "performance"
        # A mismatch that outlasts the settling deadline is still a failure.
        with patch("fan_control.app.GLib.get_monotonic_time", side_effect=[0, 4_000_000]):
            sync.call_args.kwargs["finished"](None)
        window.fail.assert_called_once()
        window.toast_overlay.add_toast.assert_not_called()

    def test_profile_readback_waits_for_desktop_transition_to_finish(self):
        from fan_control.app import FanWindow
        window = self.window()
        window.busy = True
        window.hardware = HostHardware()
        window.hardware.verify_async = MagicMock()
        request = DemoHardware().profile_request("quiet")
        with patch("fan_control.app.sync_to_desktop") as sync, \
             patch("fan_control.app.GLib.timeout_add", return_value=42) as schedule:
            FanWindow.complete_write(window, request, "Quiet applied")
            sync.call_args.kwargs["finished"](None)
            first_readback = window.hardware.verify_async.call_args.args[1]
            first_readback(ValueError("The setting did not stay applied."))
            window.fail.assert_not_called()
            self.assertTrue(window.busy)
            schedule.assert_called_once()
            self.assertEqual(schedule.call_args.args[1](), GLib.SOURCE_REMOVE)
            final_readback = window.hardware.verify_async.call_args.args[1]
            final_readback(None)
        self.assertFalse(window.busy)
        window.fail.assert_not_called()
        window.toast_overlay.add_toast.assert_called_once()

    def test_outgoing_sync_failure_is_visible(self):
        from fan_control.app import FanWindow
        window = self.window()
        request = window.hardware.profile_request("balanced")
        with patch("fan_control.app.is_live_hardware", return_value=True), \
             patch("fan_control.app.sync_to_desktop") as sync:
            FanWindow.complete_write(window, request, "Balanced applied")
        sync.call_args.kwargs["finished"](ValueError("Desktop refused change"))
        self.assertIn("Desktop refused change", window.fail.call_args.args[0])
        window.toast_overlay.add_toast.assert_not_called()

    def test_new_desktop_choice_supersedes_outgoing_sync(self):
        from fan_control.app import FanWindow
        window = self.window()
        window.pending_desktop_profile = "performance"
        request = window.hardware.profile_request("balanced")
        with patch("fan_control.app.is_live_hardware", return_value=True), \
             patch("fan_control.app.sync_to_desktop") as sync, \
             patch("fan_control.app.GLib.timeout_add", return_value=42):
            FanWindow.complete_write(window, request, "Balanced applied")
        sync.assert_not_called()
        self.assertEqual(window.pending_desktop_profile, "performance")

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
        finished = MagicMock()
        sync_to_desktop("cool", bus=mock_bus, finished=finished)
        finished.assert_called_once_with(None)
        mock_bus.call.assert_not_called()

        sync_to_desktop("unknown", bus=mock_bus)
        mock_bus.call.assert_not_called()

    def test_sync_to_desktop_handles_missing_bus_or_dbus_errors(self):
        finished = MagicMock()
        with patch("fan_control.power_profiles.get_system_bus", return_value=None):
            sync_to_desktop("balanced", finished=finished)
        self.assertIsInstance(finished.call_args.args[0], ValueError)

        failing_bus = MagicMock()
        failing_bus.call.side_effect = RuntimeError("D-Bus failure")
        finished.reset_mock()
        sync_to_desktop("balanced", bus=failing_bus, finished=finished)
        finished.assert_called_once_with(failing_bus.call.side_effect)

    def test_sync_to_desktop_reports_async_success_and_failure(self):
        for error in (None, RuntimeError("Access denied")):
            with self.subTest(error=error):
                bus = MagicMock()
                bus.call_finish.side_effect = error
                finished = MagicMock()
                sync_to_desktop("balanced", bus=bus, finished=finished)
                finished.assert_not_called()
                args = bus.call.call_args.args
                self.assertEqual(args[7], 3000)
                args[9](bus, object())
                finished.assert_called_once_with(error)

    def test_subscribe_and_unsubscribe_desktop_changes(self):
        mock_bus = MagicMock()
        mock_bus.signal_subscribe.return_value = 42

        received = []
        sub_id = subscribe_desktop_changes(lambda p: received.append(p), bus=mock_bus)
        self.assertEqual(sub_id, 42)
        mock_bus.signal_subscribe.assert_called_once()

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
