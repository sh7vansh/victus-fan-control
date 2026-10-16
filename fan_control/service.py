"""Install and manage the system daemon through an explicit administrator prompt."""

import os
from pathlib import Path
import shlex
import subprocess
from gi.repository import Gio

from .native import FLATPAK_INFO, host_helper_path

DAEMON_SOCKET = Path("/run/victus-fan-control.sock")
UNIT_PATH = Path("/etc/systemd/system/victus-fan-control.service")
INSTALLED_HELPER = Path("/usr/local/libexec/victus-fan-control/helper")


def is_service_active(socket_path: Path = DAEMON_SOCKET) -> bool:
    """Check the host service, with a bound on synchronous status queries."""
    try:
        cmd = host_command_argv("systemctl", "is-active", "--quiet", "victus-fan-control.service")
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return socket_path.exists()


def service_unit_content(helper_path: Path = INSTALLED_HELPER, allowed_uid: int | None = None) -> str:
    """Only a root-owned installed executable may be used by the persistent unit."""
    uid = os.getuid() if allowed_uid is None else allowed_uid
    if type(uid) is not int or not 0 <= uid < 2**32:
        raise ValueError("Invalid authorized user ID.")
    # systemd has its own quoting and specifier expansion rules.
    helper = str(helper_path).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$")
    if "\n" in helper or "\r" in helper:
        raise ValueError("Invalid helper path.")
    return (
        "[Unit]\n"
        "Description=HP Victus and OMEN Fan Control Daemon\n\n"
        "[Service]\n"
        "Type=simple\n"
        f'ExecStart="{helper}" --daemon --allow-uid {uid}\n'
        "Restart=on-failure\n"
        "RestartSec=2s\n"
        "UMask=0077\n"
        "NoNewPrivileges=yes\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def host_command_argv(*cmd, privileged=False):
    argv = list(cmd)
    if privileged:
        argv = ["/usr/bin/pkexec", "--disable-internal-agent", *argv]
    if FLATPAK_INFO.exists():
        prefix = ["/usr/bin/flatpak-spawn", "--host"]
        if privileged:
            prefix.append("--watch-bus")
        argv = [*prefix, *argv]
    return argv


def installation_script(helper: Path, allowed_uid: int, unit_path: Path = UNIT_PATH,
                        installed_helper: Path = INSTALLED_HELPER) -> str:
    """Stage root-owned files atomically; never execute from a user deployment."""
    quote = shlex.quote
    content = service_unit_content(installed_helper, allowed_uid)
    directory = quote(str(installed_helper.parent))
    unit_directory = quote(str(unit_path.parent))
    return (
        "set -eu\n"
        f"install -d -o 0 -g 0 -m 0755 -- {directory}\n"
        f"helper_tmp=$(mktemp {directory}/.helper.XXXXXX)\n"
        f"unit_tmp=$(mktemp {unit_directory}/.victus-unit.XXXXXX)\n"
        "trap 'rm -f -- \"$helper_tmp\" \"$unit_tmp\"' EXIT\n"
        f"install -o 0 -g 0 -m 0755 -- {quote(str(helper))} \"$helper_tmp\"\n"
        f"mv -fT -- \"$helper_tmp\" {quote(str(installed_helper))}\n"
        f"restorecon {quote(str(installed_helper))} 2>/dev/null || true\n"
        f"printf %s {quote(content)} > \"$unit_tmp\"\n"
        "chown 0:0 \"$unit_tmp\"\n"
        "chmod 0644 \"$unit_tmp\"\n"
        f"mv -fT -- \"$unit_tmp\" {quote(str(unit_path))}\n"
        f"restorecon {quote(str(unit_path))} 2>/dev/null || true\n"
        "systemctl daemon-reload\n"
        "systemctl enable victus-fan-control.service\n"
        "systemctl restart victus-fan-control.service\n"
    )


def _run_privileged_script(script, callback):
    try:
        argv = host_command_argv("/usr/bin/sh", "-c", script, privileged=True)
        flags = Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
        proc = Gio.Subprocess.new(argv, flags)
    except Exception as error:
        callback(error)
        return

    def finished(proc, result):
        error = None
        try:
            _, output, errors = proc.communicate_utf8_finish(result)
            if not proc.get_successful():
                error = ValueError((errors or output or "The service command failed.").strip())
        except Exception as failure:
            error = failure
        callback(error)

    proc.communicate_utf8_async(None, None, finished)


def install_service_async(callback, helper_path: Path | None = None, unit_path: Path = UNIT_PATH):
    try:
        script = installation_script(helper_path or host_helper_path(), os.getuid(), unit_path)
    except Exception as error:
        callback(error)
        return
    _run_privileged_script(script, callback)


def uninstall_service_async(callback, socket_path: Path = DAEMON_SOCKET, unit_path: Path = UNIT_PATH):
    quote = shlex.quote
    script = (
        "set -eu\n"
        "systemctl disable --now victus-fan-control.service\n"
        f"rm -f -- {quote(str(unit_path))} {quote(str(socket_path))} {quote(str(INSTALLED_HELPER))}\n"
        f"rmdir -- {quote(str(INSTALLED_HELPER.parent))} 2>/dev/null || true\n"
        "systemctl daemon-reload\n"
    )
    _run_privileged_script(script, callback)
