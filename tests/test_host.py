import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from gi.repository import GLib

from fan_control.host import HostHardware, READ_SCRIPT, parse_snapshot
import test_hardware


def sample():
    return {"profile": "balanced", "choices": ["quiet", "cool", "balanced", "performance"],
            "controller": "/sys/devices/platform/hp-wmi/hwmon/hwmon42", "mode": 2,
            "rpm": [0, 2576], "labels": ["CPU fan", "GPU fan"]}


class HostTests(unittest.TestCase):
    def setUp(self):
        self.host = HostHardware()
        self.host.snapshot = parse_snapshot(json.dumps(sample()))
        self.host.available = True

    def run_read(self, argv, timeout_ms=3000):
        loop = GLib.MainLoop()
        result = []

        def finished(output, error):
            result.append((output, error))
            loop.quit()

        HostHardware.read_command(argv, finished, timeout_ms)
        if not result:
            loop.run()
        self.assertEqual(len(result), 1)
        return result[0]

    def test_host_reads_need_no_installed_python_app_or_import_path(self):
        fixture = test_hardware.HardwareTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        script = "import sys\n" + READ_SCRIPT.replace("Hardware().read()", "Hardware(Path(sys.argv[1])).read()")
        result = subprocess.run([sys.executable, "-I", "-c", script, str(fixture.root)],
                                check=True, capture_output=True, text=True)
        state = json.loads(result.stdout)
        self.assertEqual(state["profile"], "balanced")
        self.assertEqual(state["rpm"], [0, 2576])
        self.assertEqual(fixture.hardware.read().profile, "balanced")
        self.assertEqual(fixture.hardware.read().mode, 2)

    def test_only_validated_settings_become_write_requests(self):
        request = self.host.profile_request("quiet")
        self.assertEqual(request.value, "quiet")
        self.assertEqual(self.host.fan_request(True).value, "0")
        self.assertEqual(self.host.fan_request(False).value, "2")
        self.assertEqual(self.host.fan_request(True).path, Path(sample()["controller"]) / "pwm1_enable")
        for invalid in ("quiet\nperformance", "/etc/passwd", "custom", ""):
            with self.assertRaises(ValueError):
                self.host.profile_request(invalid)
        self.host.available = False
        with self.assertRaises(ValueError):
            self.host.fan_request(True)

    def test_controller_paths_outside_hp_are_rejected(self):
        for path in ("/etc", "/sys/devices/platform/other/hwmon/hwmon42",
                     "/sys/devices/platform/hp-wmi/hwmon/../../other", "relative/hwmon6"):
            state = sample()
            state["controller"] = path
            with self.subTest(path=path), self.assertRaises(ValueError):
                parse_snapshot(json.dumps(state))

    def test_invalid_readings_are_rejected_and_missing_values_remain_missing(self):
        state = sample()
        state.update(controller=None, mode=None, rpm=[None, 0])
        result = parse_snapshot(json.dumps(state))
        self.assertEqual(result.rpm, (None, 0))
        for bad in ([1], [True, 0], [-1, 4], ["0", 4]):
            state["rpm"] = bad
            with self.assertRaises(ValueError):
                parse_snapshot(json.dumps(state))

    def test_async_reader_reports_output_failure_and_timeout(self):
        output, error = self.run_read([sys.executable, "-c", "print('balanced')"])
        self.assertIsNone(error)
        self.assertEqual(output.strip(), "balanced")
        _, error = self.run_read([sys.executable, "-c", "import sys; sys.stderr.write('denied'); sys.exit(1)"])
        self.assertIn("denied", str(error))
        _, error = self.run_read([sys.executable, "-c", "import time; time.sleep(10)"], timeout_ms=50)
        self.assertIn("Timed out", str(error))

    def test_poll_clears_stale_hardware_when_host_access_fails_and_recovers(self):
        completed = []
        with patch.object(HostHardware, "read_command", side_effect=lambda argv, done: done("", ValueError("denied"))):
            self.host.poll(lambda: completed.append(True))
        self.assertFalse(self.host.available)
        self.assertIsNone(self.host.read().profile)
        self.assertEqual(self.host.error, "denied")
        self.assertFalse(self.host.pending)
        with patch.object(HostHardware, "read_command", side_effect=lambda argv, done: done(json.dumps(sample()), None)):
            self.host.poll(lambda: completed.append(True))
        self.assertTrue(self.host.available)
        self.assertEqual(self.host.read().profile, "balanced")
        self.assertIsNone(self.host.error)
        self.assertEqual(len(completed), 2)

    def test_readback_uses_the_host_and_detects_external_changes(self):
        request = self.host.profile_request("quiet")
        outcomes = []
        argv_seen = []

        def command(argv, done):
            argv_seen.append(argv)
            done("balanced\n", None)

        with patch.object(HostHardware, "read_command", side_effect=command):
            self.host.verify_async(request, outcomes.append)
        self.assertIn("did not stay applied", str(outcomes[0]))
        self.assertEqual(argv_seen[0], ["/usr/bin/flatpak-spawn", "--host", "/usr/bin/cat", "--", str(request.path)])
        with patch.object(HostHardware, "read_command", side_effect=lambda argv, done: done("quiet\n", None)):
            self.host.verify_async(request, outcomes.append)
        self.assertIsNone(outcomes[1])


if __name__ == "__main__":
    unittest.main()
