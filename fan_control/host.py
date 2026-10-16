"""Flatpak host bridge. Read as the user; authenticate only sysfs writes."""

import json
from pathlib import Path

from gi.repository import Gio, GLib

from .hardware import PROFILES, Snapshot, WriteRequest


SPAWN = ["/usr/bin/flatpak-spawn", "--host"]
PROFILE_PATH = Path("/sys/firmware/acpi/platform_profile")

# Run a copy of our read-only discovery logic as the normal host user. Passing
# the code directly needs no host installation and no access to the checkout.
# Privileged changes use the separate session helper; this code stays unprivileged.
READ_SCRIPT = Path(__file__).with_name("hardware.py").read_text() + """
import json
from dataclasses import asdict
state = asdict(Hardware().read())
state['controller'] = str(state['controller']) if state['controller'] else None
print(json.dumps(state))
"""


def empty_snapshot():
    return Snapshot(None, (), None, None, (None, None), ("CPU fan", "GPU fan"))


def parse_snapshot(output):
    state = json.loads(output)
    controller = Path(state["controller"]) if state["controller"] else None
    if controller is not None:
        expected = Path("/sys/devices/platform/hp-wmi/hwmon")
        if controller.parent != expected or not controller.name.startswith("hwmon") or not controller.name[5:].isdigit():
            raise ValueError("The host returned an unexpected fan controller path.")
    profile = state["profile"]
    choices = state["choices"]
    mode = state["mode"]
    rpm = state["rpm"]
    labels = state["labels"]
    if (profile is not None and not isinstance(profile, str)) or not isinstance(choices, list) or not all(isinstance(p, str) for p in choices):
        raise ValueError("The host returned invalid thermal profile data.")
    if (mode is not None and (type(mode) is not int or mode < 0)) or not isinstance(rpm, list) or len(rpm) != 2 or any(v is not None and (type(v) is not int or v < 0) for v in rpm):
        raise ValueError("The host returned invalid fan readings.")
    if not isinstance(labels, list) or len(labels) != 2 or not all(isinstance(label, str) for label in labels):
        raise ValueError("The host returned invalid fan labels.")
    return Snapshot(profile, tuple(choices), controller, mode, tuple(rpm), tuple(labels))


class HostHardware:
    def __init__(self):
        self.snapshot = empty_snapshot()
        self.pending = False
        self.available = False
        self.error = None

    def read(self):
        return self.snapshot

    def poll(self, updated):
        if self.pending:
            return
        self.pending = True

        def finished(output, error):
            try:
                if error is not None:
                    raise error
                self.snapshot = parse_snapshot(output)
                self.available = True
                self.error = None
            except (ValueError, KeyError, TypeError, OSError) as error:
                self.snapshot = empty_snapshot()
                self.available = False
                self.error = str(error)
            finally:
                self.pending = False
            updated()

        self.read_command([*SPAWN, "/usr/bin/python3", "-I", "-c", READ_SCRIPT], finished)

    def profile_request(self, value):
        if not self.available or self.snapshot.profile is None:
            raise ValueError("Thermal profile controls are unavailable.")
        if value not in PROFILES or value not in self.snapshot.choices:
            raise ValueError("This thermal profile is not supported by your firmware.")
        return WriteRequest(PROFILE_PATH, value)

    def fan_request(self, maximum):
        if not self.available or self.snapshot.controller is None or self.snapshot.mode is None:
            raise ValueError("The HP fan controller is unavailable.")
        return WriteRequest(self.snapshot.controller / "pwm1_enable", "0" if maximum else "2")

    def verify_async(self, request, finished):
        def readback(output, error):
            if error is None and output.strip() != request.value:
                error = ValueError("The setting did not stay applied. The firmware or another power management app may have changed it.")
            finished(error)

        self.read_command([*SPAWN, "/usr/bin/cat", "--", str(request.path)], readback)

    @staticmethod
    def read_command(argv, finished, timeout_ms=3000):
        """Bounded async user-level read; the GTK main loop never waits on it."""
        flags = Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
        try:
            process = Gio.Subprocess.new(argv, flags)
        except GLib.Error as error:
            finished("", ValueError(error.message))
            return
        expired = False

        def timeout():
            nonlocal expired
            expired = True
            process.force_exit()
            return GLib.SOURCE_REMOVE

        source = GLib.timeout_add(timeout_ms, timeout)

        def communicated(process, result):
            if not expired:
                GLib.source_remove(source)
            try:
                _, output, errors = process.communicate_utf8_finish(result)
                if expired:
                    raise ValueError("Timed out reading laptop settings from the host.")
                if not process.get_successful():
                    raise ValueError((errors or "The host refused access. Check this app’s host-command permission.").strip())
            except (GLib.Error, ValueError) as error:
                finished("", ValueError(str(error)))
                return
            finished(output or "", None)

        process.communicate_utf8_async(None, None, communicated)
