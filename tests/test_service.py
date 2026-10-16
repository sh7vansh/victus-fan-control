import unittest
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fan_control.service import (
    DAEMON_SOCKET,
    UNIT_PATH,
    host_command_argv,
    is_service_active,
    service_unit_content,
    installation_script,
    INSTALLED_HELPER,
)


class ServiceTests(unittest.TestCase):
    def test_service_unit_content_contains_daemon_flag_and_helper(self):
        helper = Path("/custom/path/victus-fan-control-helper")
        content = service_unit_content(helper, allowed_uid=1001)
        self.assertIn('[Unit]', content)
        self.assertIn('ExecStart="/custom/path/victus-fan-control-helper" --daemon --allow-uid 1001\n', content)
        self.assertIn('Restart=on-failure', content)
        self.assertIn('WantedBy=multi-user.target', content)

    def test_installer_copies_helper_and_restarts_existing_service(self):
        helper = Path("/home/user/app files/$(touch /tmp/unexpected) 'helper")
        script = installation_script(helper, 1001)
        subprocess.run(["/bin/sh", "-n"], input=script, text=True, check=True)
        self.assertIn('install -o 0 -g 0 -m 0755 -- ', script)
        self.assertIn(f'ExecStart="{INSTALLED_HELPER}" --daemon --allow-uid 1001', script)
        self.assertNotIn(f'ExecStart="{helper}"', script)
        self.assertIn('systemctl restart victus-fan-control.service', script)
        self.assertLess(script.index('mv -fT -- "$helper_tmp"'), script.index('systemctl restart'))

    def test_successful_install_reconnects_without_removed_method(self):
        from fan_control.app import FanWindow
        from fan_control.authorization import AuthorizationSession
        with tempfile.TemporaryDirectory() as directory:
            socket_path = Path(directory) / "visible.sock"
            socket_path.touch()
            session = AuthorizationSession(socket_path=None)
            session.socket_path = socket_path
            session.connect = Mock()
            window = SimpleNamespace(authorization=session, update_authorization=Mock(),
                                     toast_overlay=Mock())
            with patch("fan_control.app.FLATPAK_INFO", Path(directory) / "absent"):
                FanWindow._on_service_installed(window, None)
            session.connect.assert_called_once()
            window.update_authorization.assert_called_once()

    def test_flatpak_install_requests_restart_even_when_old_socket_is_visible(self):
        from fan_control.app import FanWindow
        from fan_control.authorization import AuthorizationSession
        with tempfile.TemporaryDirectory() as directory:
            visible = Path(directory) / "socket-and-flatpak-marker"
            visible.touch()
            session = AuthorizationSession(socket_path=None)
            session.socket_path = visible
            session.connect = Mock()
            window = SimpleNamespace(authorization=session, update_authorization=Mock())
            with patch("fan_control.app.FLATPAK_INFO", visible), patch("fan_control.app.Adw.AlertDialog.new") as create:
                FanWindow._on_service_installed(window, None)
            session.connect.assert_not_called()
            create.return_value.present.assert_called_once_with(window)

    def test_service_command_failure_is_reported_once_with_details(self):
        from fan_control.service import _run_privileged_script
        process = Mock()
        process.communicate_utf8_finish.return_value = (True, "", "Service failed to start")
        process.get_successful.return_value = False
        callback = Mock()
        with patch("fan_control.service.Gio.Subprocess.new", return_value=process):
            _run_privileged_script("exit 1", callback)
        completed = process.communicate_utf8_async.call_args.args[2]
        completed(process, None)
        callback.assert_called_once()
        self.assertIn("Service failed to start", str(callback.call_args.args[0]))

    def test_host_command_argv_outside_flatpak(self):
        with patch.object(Path, "exists", return_value=False):
            argv = host_command_argv("systemctl", "status", "test", privileged=False)
            self.assertEqual(argv, ["systemctl", "status", "test"])

            privileged_argv = host_command_argv("systemctl", "enable", privileged=True)
            self.assertEqual(privileged_argv, ["/usr/bin/pkexec", "--disable-internal-agent", "systemctl", "enable"])

    def test_host_command_argv_inside_flatpak(self):
        with patch.object(Path, "exists", return_value=True):
            argv = host_command_argv("systemctl", "status", privileged=False)
            self.assertEqual(argv, ["/usr/bin/flatpak-spawn", "--host", "systemctl", "status"])

            privileged_argv = host_command_argv("systemctl", "enable", privileged=True)
            self.assertEqual(privileged_argv, [
                "/usr/bin/flatpak-spawn", "--host", "--watch-bus",
                "/usr/bin/pkexec", "--disable-internal-agent",
                "systemctl", "enable"
            ])

    def test_is_service_active_checks_socket(self):
        fake_socket = Path("/tmp/fake-nonexistent-victus-test.sock")
        with patch("fan_control.service.subprocess.run", return_value=SimpleNamespace(returncode=3)):
            self.assertFalse(is_service_active(fake_socket))


if __name__ == "__main__":
    unittest.main()
