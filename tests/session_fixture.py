"""Run the separate Go test helper against temporary sysfs files."""

from pathlib import Path
import subprocess
import time

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


class FixtureDaemon:
    def __init__(self, root, launched):
        self.socket_path = root / "daemon.sock"
        self.process = subprocess.Popen(
            [str(TEST_HELPER), "--", "daemon", str(root), str(self.socket_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        launched.append(True)
        for _ in range(200):
            if self.socket_path.exists():
                break
            if self.process.poll() is not None:
                raise RuntimeError(self.process.stderr.read().decode())
            time.sleep(0.01)
        else:
            self.close()
            raise RuntimeError("Fixture daemon did not start")

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
        self.process.wait(timeout=5)
        self.process.stderr.close()


def fixture_session(root, launched):
    daemon = FixtureDaemon(root, launched)
    session = AuthorizationSession(socket_path=daemon.socket_path)
    session.fixture_daemon = daemon
    return session
