import unittest
from pathlib import Path
from unittest.mock import patch

from fan_control.service import (
    DAEMON_SOCKET,
    UNIT_PATH,
    host_command_argv,
    is_service_active,
    service_unit_content,
)


class ServiceTests(unittest.TestCase):
    def test_service_unit_content_contains_daemon_flag_and_helper(self):
        helper = Path("/custom/path/victus-fan-control-helper")
        content = service_unit_content(helper)
        self.assertIn('[Unit]', content)
        self.assertIn('ExecStart="/custom/path/victus-fan-control-helper" --daemon', content)
        self.assertIn('Restart=on-failure', content)
        self.assertIn('WantedBy=multi-user.target', content)

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
        self.assertFalse(is_service_active(fake_socket))


if __name__ == "__main__":
    unittest.main()
