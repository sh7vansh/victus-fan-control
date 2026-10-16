"""Short-lived fan-only privileged process; no package imports or shell commands.

The app sends this source to the host's isolated Python via pkexec. The protocol
accepts enumerated operations, never paths, executable names, or Python code.
"""

import json
import os
from pathlib import Path
import select
import sys
import time

PROFILES = frozenset(("quiet", "cool", "balanced", "performance"))
MAX_LINE = 1024
IDLE_SECONDS = 20


class SysfsControls:
    def __init__(self, root=Path("/sys")):
        self.root = root

    def change(self, operation, value):
        if operation == "profile":
            if value not in PROFILES:
                raise ValueError("Unsupported thermal profile.")
            path = self.root / "firmware/acpi/platform_profile"
            choices = path.with_name("platform_profile_choices").read_text().split()
            if value not in choices:
                raise ValueError("This profile is not supported by your firmware.")
        elif operation == "fan":
            if value not in ("0", "2"):
                raise ValueError("Only maximum and automatic fan modes are supported.")
            parent = self.root / "devices/platform/hp-wmi/hwmon"
            path = None
            for candidate in sorted(parent.glob("hwmon*")):
                target = candidate.resolve(strict=True)
                if (target.parent == parent and target.name[5:].isdigit()
                        and (target / "name").read_text().strip() == "hp"):
                    path = target / "pwm1_enable"
                    break
            if path is None:
                raise ValueError("The HP fan controller is unavailable.")
        else:
            raise ValueError("Unknown fan-control operation.")
        # No client-controlled paths or file creation, even with malformed input.
        descriptor = os.open(path, os.O_WRONLY | os.O_TRUNC | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            payload = (value + "\n").encode("ascii")
            if os.write(descriptor, payload) != len(payload):
                raise OSError("The firmware accepted only part of the setting.")
        finally:
            os.close(descriptor)


def dispatch(message, controls):
    if not isinstance(message, dict):
        raise ValueError("Expected a fan-control request.")
    if set(message) != {"id", "operation", "value"}:
        raise ValueError("Unexpected request fields.")
    request_id = message["id"]
    if type(request_id) is not int or not 0 < request_id <= 2**53:
        raise ValueError("Invalid request identifier.")
    operation, value = message["operation"], message["value"]
    if type(operation) is not str or type(value) is not str:
        raise ValueError("Invalid fan-control setting.")
    if operation == "profile" and value not in PROFILES:
        raise ValueError("Unsupported thermal profile.")
    if operation == "fan" and value not in ("0", "2"):
        raise ValueError("Only maximum and automatic fan modes are supported.")
    if operation not in ("profile", "fan"):
        raise ValueError("Unknown fan-control operation.")
    controls.change(operation, value)


def serve(controls, idle_seconds=IDLE_SECONDS):
    def reply(message):
        print(json.dumps(message), flush=True)

    reply({"ready": True})
    deadline = time.monotonic() + idle_seconds
    buffer = b""
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([sys.stdin.fileno()], [], [], remaining)[0]:
            return
        chunk = os.read(sys.stdin.fileno(), MAX_LINE + 1)
        if not chunk:
            return
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            if len(line) > MAX_LINE:
                return
            message = None
            try:
                message = json.loads(line)
                if message == {"operation": "ping"}:
                    deadline = time.monotonic() + idle_seconds
                    continue
                if message == {"operation": "close"}:
                    return
                dispatch(message, controls)
                deadline = time.monotonic() + idle_seconds
                reply({"id": message["id"], "ok": True})
            except (ValueError, TypeError, KeyError, OSError) as error:
                request_id = message.get("id") if isinstance(message, dict) else None
                reply({"id": request_id, "ok": False, "error": str(error)})
        if len(buffer) > MAX_LINE:
            return


def main():
    if os.geteuid() != 0:
        raise SystemExit("Administrator authentication is required for fan changes.")
    try:
        serve(SysfsControls())
    except (BrokenPipeError, ConnectionResetError):
        pass


if __name__ == "__main__":
    main()
