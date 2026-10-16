"""GTK integration tests for the host backend."""

from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fan_control.app import FanApplication, FanWindow
from fan_control.host import HostHardware, PROFILE_PATH
from gi.repository import Gio, GLib
from session_fixture import fixture_session, fixture_argv
import test_hardware


class FixtureHostHardware(HostHardware):
    def __init__(self, fixture):
        super().__init__()
        self.fixture = fixture

    def local_path(self, host_path):
        if Path(host_path) == PROFILE_PATH:
            return self.fixture.hardware.profile_path
        if Path(host_path) == Path("/sys/devices/platform/hp-wmi/hwmon/hwmon42/pwm1_enable"):
            return self.fixture.controller / "pwm1_enable"
        raise AssertionError(f"Unexpected write/readback path: {host_path}")

    def read_command(self, argv, finished, timeout_ms=3000):
        if argv[-1] == "--snapshot":
            command = fixture_argv(self.fixture.root, mode="snapshot")
        else:
            operation, value = argv[-2:]
            assert operation in ("--verify-profile", "--verify-fan")
            command = fixture_argv(self.fixture.root, mode=operation[2:], value=value)
        HostHardware.read_command(command, finished, timeout_ms)


class HostApplication(FanApplication):
    def __init__(self, fixture):
        super().__init__(demo=True)
        self.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
        self.hardware = FixtureHostHardware(fixture)
        self.fixture = fixture
        self.stage = 0
        self.ticks = 0
        self.launches = []
        self.authorization_factory = lambda: fixture_session(fixture.root, self.launches)
        self.command = "write"

    @property
    def command(self):
        return (self.fixture.root / "test-command").read_text()

    @command.setter
    def command(self, value):
        (self.fixture.root / "test-command").write_text(value)

    def do_activate(self):
        self.window = FanWindow(self, self.hardware)
        self.window.present()
        GLib.timeout_add(500, self.advance)

    def advance(self):
        self.ticks += 1
        try:
            assert self.ticks < 40, "GTK host integration timed out"
            w = self.window
            if w.busy or not self.hardware.available or self.hardware.pending:
                return GLib.SOURCE_CONTINUE
            if self.stage == 0:
                assert w.snapshot.profile == "balanced" and w.snapshot.rpm == (0, 2576)
                w.profile_buttons["quiet"].set_active(True)
            elif self.stage == 1:
                assert w.snapshot.profile == "quiet" and not w.error_banner.get_revealed()
                w.maximum.set_active(True)
            elif self.stage == 2:
                assert w.snapshot.mode == 0 and w.maximum.get_active()
                w.maximum.set_active(False)
            elif self.stage == 3:
                assert w.snapshot.mode == 2 and not w.maximum.get_active()
                assert len(self.launches) == 1, "Repeated changes started more than one daemon"
                w.authorization.close()
                assert not w.authorization.unlocked
                self.command = "reject"
                w.maximum.set_active(True)
            elif self.stage == 4:
                assert w.snapshot.mode == 2 and not w.maximum.get_active()
                assert w.error_banner.get_revealed()
                assert w.authorization.unlocked, "Client did not reconnect to daemon"
                self.command = "reject"
                w.profile_buttons["performance"].set_active(True)
            elif self.stage == 5:
                assert w.error_banner.get_revealed() and w.snapshot.profile == "quiet"
                assert w.profile_buttons["quiet"].get_active()
                self.command = "ignore"
                w.profile_buttons["balanced"].set_active(True)
            else:
                assert w.error_banner.get_revealed() and "did not stay applied" in w.error_detail
                assert w.snapshot.profile == "quiet" and w.profile_buttons["quiet"].get_active()
                print("GTK host integration passed: async reads, profile, max/auto, reconnection, failed writes, and host readback", flush=True)
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


fixture = test_hardware.HardwareTests()
fixture.setUp()
(fixture.root / "not-executable").write_text("not executable\n")
try:
    app = HostApplication(fixture)
    # Fixture HostHardware must never change the real desktop power profile.
    with patch("fan_control.app.sync_to_desktop"), patch("fan_control.app.subscribe_desktop_changes"):
        result = app.run([sys.argv[0]])
finally:
    if hasattr(app, "window"):
        app.window.authorization.fixture_daemon.close()
    fixture.doCleanups()
raise SystemExit(1 if app.failure else result)
