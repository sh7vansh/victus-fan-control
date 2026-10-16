"""Exercise the GTK/subprocess path against temporary files; no pkexec or sysfs writes."""

from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fan_control.app import FanApplication, FanWindow
from fan_control.hardware import Hardware, WriteRequest
from gi.repository import Gio, GLib


class IntegrationApplication(FanApplication):
    def __init__(self, root):
        super().__init__(demo=True)
        self.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
        self.hardware = Hardware(root)
        self.stage = 0
        self.ticks = 0
        self.command = "write"

    def argv(self, request):
        if self.command == "reject":
            return [sys.executable, "-c", "import sys; sys.stdin.read(); raise SystemExit(1)"]
        if self.command == "cancel":
            # env exits 126 without consuming stdin, like an early pkexec cancel.
            return ["/usr/bin/env", str(self.hardware.root / "not-executable")]
        if self.command == "ignore":
            return [sys.executable, "-c", "import sys; sys.stdin.read()"]
        return ["/usr/bin/tee", "--", str(request.path)]

    def do_activate(self):
        self.window = FanWindow(self, self.hardware)
        self.window.present()
        GLib.timeout_add(500, self.advance)

    def advance(self):
        self.ticks += 1
        try:
            assert self.ticks < 40, "Integration test timed out"
            w = self.window
            if w.busy:
                return GLib.SOURCE_CONTINUE
            if self.stage == 0:
                assert w.snapshot.profile == "balanced" and w.snapshot.rpm == (0, 2576)
                w.profile_buttons["quiet"].set_active(True)
            elif self.stage == 1:
                assert w.snapshot.profile == "quiet"
                assert w.profile_buttons["quiet"].get_active()
                w.maximum.set_active(True)
            elif self.stage == 2:
                assert w.snapshot.mode == 0 and w.maximum.get_active()
                w.maximum.set_active(False)
            elif self.stage == 3:
                assert w.snapshot.mode == 2 and not w.maximum.get_active()
                self.hardware.profile_path.write_text("cool\n")
                w.refresh()
                assert w.profile_buttons["cool"].get_active(), "External change not reflected"
                self.command = "reject"
                w.profile_buttons["quiet"].set_active(True)
            elif self.stage == 4:
                assert w.error_banner.get_revealed(), "Failed subprocess not reported"
                assert w.snapshot.profile == "cool" and w.profile_buttons["cool"].get_active()
                self.command = "cancel"
                w.maximum.set_active(True)
            elif self.stage == 5:
                assert not w.error_banner.get_revealed(), "Cancellation should be informational"
                assert w.snapshot.mode == 2 and not w.maximum.get_active()
                self.command = "ignore"
                w.profile_buttons["balanced"].set_active(True)
            elif self.stage == 6:
                assert w.error_banner.get_revealed() and "did not stay applied" in w.error_detail, repr(w.error_detail)
                assert w.snapshot.profile == "cool" and w.profile_buttons["cool"].get_active()
                controller = w.snapshot.controller
                (controller / "fan1_input").write_text("bad\n")
                (controller / "fan2_input").unlink()
                (controller / "pwm1_enable").unlink()
                self.hardware.profile_path.unlink()
                w.refresh()
                assert w.snapshot.rpm == (None, None)
                assert all(card.value.get_label() == "—" for card in w.fans)
                assert not w.maximum.get_sensitive()
                assert all(not row.get_sensitive() for row in w.profile_rows.values())
                print("GTK integration passed: async writes, max/auto mapping, external changes, failure, cancellation, readback rejection, and missing hardware", flush=True)
                w.close()
                return GLib.SOURCE_REMOVE
            self.stage += 1
        except Exception:
            import traceback
            traceback.print_exc()
            self.failure = True
            self.quit()
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE


with tempfile.TemporaryDirectory(prefix="fan-control-test-") as directory:
    root = Path(directory)
    (root / "not-executable").write_text("not executable\n")
    acpi = root / "firmware/acpi"
    acpi.mkdir(parents=True)
    (acpi / "platform_profile").write_text("balanced\n")
    (acpi / "platform_profile_choices").write_text("quiet cool balanced performance\n")
    controller = root / "devices/platform/hp-wmi/hwmon/hwmon42"
    controller.mkdir(parents=True)
    hwmon = root / "class/hwmon"
    hwmon.mkdir(parents=True)
    (hwmon / "hwmon42").symlink_to(controller)
    for name, value in {"name": "hp", "fan1_input": "0", "fan2_input": "2576", "pwm1_enable": "2"}.items():
        (controller / name).write_text(value + "\n")
    app = IntegrationApplication(root)
    with patch.object(WriteRequest, "argv", new=property(app.argv)):
        result = app.run([sys.argv[0]])
    raise SystemExit(1 if app.failure else result)
