"""Use the compiled test executable against temporary sysfs, without pkexec.

Its alternate root and error injection exist only in Go _test.go code, which is
absent from the production executable installed in the Flatpak.
"""

from pathlib import Path
import sys

from fan_control.authorization import AuthorizationSession

ROOT = Path(__file__).resolve().parent.parent
TEST_HELPER = ROOT / "build/native/fan-control-helper-tests"


def fixture_argv(root, idle_seconds=20, mode="session", value=None):
    argv = [str(TEST_HELPER), "--", mode, str(root)]
    if mode == "session":
        argv.append(str(int(idle_seconds * 1000)))
    elif value is not None:
        argv.append(value)
    return argv


def fixture_session(root, launched):
    def argv():
        launched.append(True)
        mode_path = root / "test-command"
        if mode_path.exists() and mode_path.read_text() == "cancel":
            return [sys.executable, "-I", "-c", "raise SystemExit(126)"]
        return fixture_argv(root)
    return AuthorizationSession(argv_factory=argv)
