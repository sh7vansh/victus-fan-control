"""Manage the background fan control system service (systemd unit)."""

from pathlib import Path
import subprocess
from gi.repository import Gio

from .native import FLATPAK_INFO, host_helper_path

DAEMON_SOCKET = Path("/run/victus-fan-control.sock")
UNIT_PATH = Path("/etc/systemd/system/victus-fan-control.service")


def is_service_active(socket_path: Path = DAEMON_SOCKET) -> bool:
    """Check if the background daemon service is active on the system."""
    try:
        cmd = host_command_argv("systemctl", "is-active", "--quiet", "victus-fan-control.service", privileged=False)
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return result.returncode == 0
    except (FileNotFoundError, OSError):
        return socket_path.exists()


def service_unit_content(helper_path: Path) -> str:
    """Generate the systemd service unit pointing to the host helper."""
    return (
        "[Unit]\n"
        "Description=HP Victus and OMEN Fan Control Daemon\n"
        "After=multi-user.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f'ExecStart="{helper_path}" --daemon\n'
        "Restart=on-failure\n"
        "RestartSec=2s\n\n"
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


def _on_proc_finished(proc, result, callback):
    try:
        proc.wait_check_finish(result)
        callback(None)
    except Exception as error:
        callback(error)


def install_service_async(callback, helper_path: Path | None = None, unit_path: Path = UNIT_PATH):
    """Install and enable the systemd service unit via pkexec."""
    try:
        helper = helper_path or host_helper_path()
        content = service_unit_content(helper)
        setup_script = (
            f"cat << 'EOF' > {unit_path}\n{content}EOF\n"
            f'chcon -t bin_t "{helper}" 2>/dev/null || true\n'
            "systemctl daemon-reload && systemctl enable --now victus-fan-control.service\n"
        )
        argv = host_command_argv("/usr/bin/sh", "-c", setup_script, privileged=True)
        flags = Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
        proc = Gio.Subprocess.new(argv, flags)
        proc.wait_check_async(None, lambda p, res: _on_proc_finished(p, res, callback))
    except Exception as error:
        callback(error)


def uninstall_service_async(callback, socket_path: Path = DAEMON_SOCKET, unit_path: Path = UNIT_PATH):
    """Disable and remove the systemd service unit via pkexec."""
    try:
        uninstall_script = (
            "systemctl disable --now victus-fan-control.service 2>/dev/null || true\n"
            f"rm -f {unit_path} {socket_path}\n"
            "systemctl daemon-reload\n"
        )
        argv = host_command_argv("/usr/bin/sh", "-c", uninstall_script, privileged=True)
        flags = Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
        proc = Gio.Subprocess.new(argv, flags)
        proc.wait_check_async(None, lambda p, res: _on_proc_finished(p, res, callback))
    except Exception as error:
        callback(error)
