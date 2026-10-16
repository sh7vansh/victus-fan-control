from pathlib import Path
import tempfile
import unittest

from fan_control.hardware import Hardware, WriteRequest


class HardwareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.acpi = self.root / "firmware/acpi"
        self.acpi.mkdir(parents=True)
        (self.acpi / "platform_profile").write_text("balanced\n")
        (self.acpi / "platform_profile_choices").write_text("cool quiet balanced performance\n")
        self.controller = self.root / "devices/platform/hp-wmi/hwmon/hwmon42"
        self.controller.mkdir(parents=True)
        (self.root / "class/hwmon").mkdir(parents=True)
        (self.root / "class/hwmon/hwmon42").symlink_to(self.controller)
        for name, value in {"name": "hp", "fan1_input": "0", "fan2_input": "2576", "pwm1_enable": "2"}.items():
            (self.controller / name).write_text(value + "\n")
        self.hardware = Hardware(self.root)

    def test_discovers_hp_controller_and_distinguishes_stopped_from_unavailable(self):
        result = self.hardware.read()
        self.assertEqual(result.controller, self.controller)
        self.assertEqual(result.rpm, (0, 2576))
        (self.controller / "fan2_input").unlink()
        self.assertEqual(self.hardware.read().rpm, (0, None))

    def test_recovers_after_hwmon_is_renumbered(self):
        (self.root / "class/hwmon/hwmon42").unlink()
        new_controller = self.controller.with_name("hwmon99")
        self.controller.rename(new_controller)
        (self.root / "class/hwmon/hwmon99").symlink_to(new_controller)
        self.assertEqual(self.hardware.read().controller, new_controller)
        self.assertEqual(self.hardware.fan_request(True).path, new_controller / "pwm1_enable")

    def test_never_uses_a_different_driver_even_if_named_hp(self):
        (self.root / "class/hwmon/hwmon42").unlink()
        other = self.root / "devices/platform/other-driver/hwmon/hwmon6"
        other.mkdir(parents=True)
        (other / "name").write_text("hp\n")
        (other / "pwm1_enable").write_text("2\n")
        (self.root / "class/hwmon/hwmon6").symlink_to(other)
        self.assertIsNone(self.hardware.read().controller)
        with self.assertRaises(ValueError):
            self.hardware.fan_request(True)

    def test_rejects_unsupported_profile_and_arbitrary_input(self):
        for value in ("custom", "quiet\nperformance", "../../etc/passwd", "", "low-power"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.hardware.profile_request(value)
        (self.acpi / "platform_profile_choices").write_text("balanced quiet\n")
        with self.assertRaises(ValueError):
            self.hardware.profile_request("performance")

    def test_fan_modes_are_maximum_and_automatic_only(self):
        self.assertEqual(self.hardware.fan_request(True).value, "0")
        self.assertEqual(self.hardware.fan_request(False).value, "2")
        self.assertEqual((self.controller / "pwm1_enable").read_text(), "2\n")

    def test_missing_hardware_and_invalid_readings_are_not_zero(self):
        (self.controller / "fan1_input").write_text("invalid\n")
        (self.controller / "fan2_input").write_text("-1\n")
        self.assertEqual(self.hardware.read().rpm, (None, None))
        (self.controller / "pwm1_enable").unlink()
        with self.assertRaises(ValueError):
            self.hardware.fan_request(False)
        (self.acpi / "platform_profile").unlink()
        with self.assertRaises(ValueError):
            self.hardware.profile_request("quiet")

    def test_readback_detects_firmware_rejection_or_external_change(self):
        request = self.hardware.profile_request("quiet")
        with self.assertRaises(ValueError):
            self.hardware.verify(request)
        request.path.write_text("quiet\n")
        self.hardware.verify(request)
        request.path.unlink()
        with self.assertRaises(ValueError):
            self.hardware.verify(request)



if __name__ == "__main__":
    unittest.main()
