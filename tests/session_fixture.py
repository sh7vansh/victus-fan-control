"""Run the production session protocol unprivileged against temporary sysfs."""

from pathlib import Path
import sys

from fan_control.authorization import AuthorizationSession

ROOT = Path(__file__).resolve().parent.parent


def fixture_argv(root, idle_seconds=20):
    # Only test fixtures call serve directly; the production entry requires root
    # and never accepts an alternative sysfs root from arguments or its protocol.
    script = f"""
import sys
from pathlib import Path
sys.path.insert(0, {str(ROOT)!r})
from fan_control.privileged import SysfsControls, serve
class FixtureControls(SysfsControls):
    def change(self, operation, value):
        mode_path = self.root / 'test-command'
        mode = mode_path.read_text() if mode_path.exists() else 'write'
        if mode == 'reject':
            raise ValueError('Fixture rejected the write')
        if mode != 'ignore':
            super().change(operation, value)
serve(FixtureControls(Path({str(root)!r})), idle_seconds={idle_seconds!r})
"""
    return [sys.executable, "-I", "-u", "-c", script]


def fixture_session(root, launched):
    def argv():
        launched.append(True)
        mode_path = root / "test-command"
        if mode_path.exists() and mode_path.read_text() == "cancel":
            return [sys.executable, "-I", "-c", "raise SystemExit(126)"]
        return fixture_argv(root)
    return AuthorizationSession(argv_factory=argv)
