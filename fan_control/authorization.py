"""One authorization session for a window's fan-control command pipe (via daemon socket or polkit helper)."""

import json
from pathlib import Path

from gi.repository import Gio, GLib

from .hardware import PROFILES
from .native import helper_argv
from .service import DAEMON_SOCKET


class AuthenticationCancelled(ValueError):
    pass


def session_argv():
    return helper_argv("--session", privileged=True)


class AuthorizationSession:
    def __init__(self, changed=lambda: None, argv_factory=session_argv,
                 heartbeat_ms=5000, reply_timeout_ms=5000,
                 socket_path: Path | None = DAEMON_SOCKET):
        self.changed = changed
        self.argv_factory = argv_factory
        self.heartbeat_ms = heartbeat_ms
        self.reply_timeout_ms = reply_timeout_ms
        self.socket_path = Path(socket_path) if socket_path is not None else None
        self.process = None
        self.connection = None
        self.input = None
        self.output_stream = None
        self.unlocked = False
        self.is_daemon = False
        self.pending = None
        self.counter = 0
        self.heartbeat = 0
        self.deadline = 0
        self.writing = False
        self._token = object()
        if self.socket_path and self.socket_path.exists():
            self._connect_socket()

    def change(self, request, finished):
        if self.pending:
            finished(ValueError("A fan-control change is already pending."))
            return
        if request.path.name == "platform_profile" and request.value in PROFILES:
            operation = "profile"
        elif request.path.name == "pwm1_enable" and request.value in ("0", "2"):
            operation = "fan"
        else:
            finished(ValueError("Unsupported fan-control request."))
            return
        self.counter += 1
        self.pending = ({"id": self.counter, "operation": operation, "value": request.value}, finished)
        if self.unlocked:
            self._send_change()
            return
        if self.connection is not None or self.process is not None:
            return
        if self.socket_path and self.socket_path.exists():
            self._connect_socket()
            return
        self._spawn_process()

    def _connect_socket(self):
        client = Gio.SocketClient.new()
        address = Gio.UnixSocketAddress.new(str(self.socket_path))
        token = object()
        self._token = token
        try:
            client.connect_async(address, None, self._on_socket_connected, token)
        except (GLib.Error, OSError):
            self.connection = None
            self.is_daemon = False
            if self.pending:
                self._spawn_process()

    def _on_socket_connected(self, client, result, token):
        if token is not self._token:
            try:
                conn = client.connect_finish(result)
                conn.close(None)
            except Exception:
                pass
            return
        try:
            self.connection = client.connect_finish(result)
            self.input = Gio.DataInputStream.new(self.connection.get_input_stream())
            self.input.set_newline_type(Gio.DataStreamNewlineType.LF)
            self.output_stream = self.connection.get_output_stream()
            self.is_daemon = True
            self._read(self.connection)
        except (GLib.Error, OSError):
            self.connection = None
            self.is_daemon = False
            if self.pending:
                self._spawn_process()

    def _spawn_process(self):
        self._token = object()
        try:
            flags = (Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE
                     | Gio.SubprocessFlags.STDERR_SILENCE)
            process = Gio.Subprocess.new(self.argv_factory(), flags)
            self.process = process
            self.input = Gio.DataInputStream.new(process.get_stdout_pipe())
            self.input.set_newline_type(Gio.DataStreamNewlineType.LF)
            self.output_stream = process.get_stdin_pipe()
            self.is_daemon = False
            self._read(process)
            process.wait_async(None, self._exited)
        except (GLib.Error, OSError) as error:
            self._fail(ValueError(str(error)))

    def _read(self, source):
        if self.input:
            self.input.read_line_async(GLib.PRIORITY_DEFAULT, None, self._received, source)

    def _received(self, stream, result, source):
        try:
            line, _ = stream.read_line_finish_utf8(result)
            if source is not (self.process or self.connection):
                return
            if line is None:
                if self.connection is source:
                    self._fail(ValueError("The fan-control daemon disconnected."))
                return
            message = json.loads(line)
            if not self.unlocked:
                if message != {"ready": True}:
                    raise ValueError("The fan-control session did not start correctly.")
                self.unlocked = True
                self.heartbeat = GLib.timeout_add(self.heartbeat_ms, self._ping)
                self.changed()
                self._send_change()
            else:
                if (not self.pending or type(message) is not dict
                        or message.get("id") != self.pending[0]["id"]
                        or type(message.get("ok")) is not bool):
                    raise ValueError("The fan-control session returned an invalid response.")
                error = None if message["ok"] else ValueError(str(message.get("error", "The firmware refused the setting.")))
                self._finish(error)
            if source is (self.process or self.connection):
                self._read(source)
        except (GLib.Error, ValueError, TypeError) as error:
            if source is (self.process or self.connection):
                self._fail(ValueError(str(error)))

    def _send_change(self):
        if self.pending is None:
            return
        self.deadline = GLib.timeout_add(self.reply_timeout_ms, self._timed_out)
        self._write(self.pending[0])

    def _write(self, message):
        source = self.process or self.connection
        if self.writing:
            GLib.timeout_add(10, self._write_when_ready, message, source)
            return
        self.writing = True
        stream = self.output_stream
        if stream:
            stream.write_all_async(
                (json.dumps(message) + "\n").encode(), GLib.PRIORITY_DEFAULT, None, self._written, source)

    def _write_when_ready(self, message, source):
        if source is not (self.process or self.connection):
            return GLib.SOURCE_REMOVE
        if self.writing:
            return GLib.SOURCE_CONTINUE
        self._write(message)
        return GLib.SOURCE_REMOVE

    def _written(self, stream, result, source):
        error = None
        try:
            stream.write_all_finish(result)
        except GLib.Error as failure:
            error = failure
        if source is not (self.process or self.connection):
            try:
                stream.close(None)
            except GLib.Error:
                pass
            return
        self.writing = False
        if error is not None and self.unlocked:
            self._fail(ValueError(str(error)))

    def _finish(self, error):
        if self.deadline:
            GLib.source_remove(self.deadline)
            self.deadline = 0
        pending, self.pending = self.pending, None
        if pending:
            pending[1](error)

    def _exited(self, process, result):
        try:
            process.wait_finish(result)
        except GLib.Error:
            pass
        if process is not self.process:
            return
        cancelled = not self.unlocked and process.get_if_exited() and process.get_exit_status() == 126
        error = (AuthenticationCancelled("Authentication cancelled") if cancelled else
                 ValueError("The fan-control session ended. Try again to authenticate. Check that polkit and the bundled helper are available."))
        self._fail(error)

    def _timed_out(self):
        self.deadline = 0
        self._fail(ValueError("Timed out changing the fan setting. The session has been locked; check the current hardware state before retrying."))
        return GLib.SOURCE_REMOVE

    def _ping(self):
        if not self.unlocked:
            self.heartbeat = 0
            return GLib.SOURCE_REMOVE
        if not self.pending and not self.writing:
            self._write({"operation": "ping"})
        return GLib.SOURCE_CONTINUE

    def _fail(self, error):
        self.close()
        self._finish(error)

    def close(self):
        for source in (self.heartbeat, self.deadline):
            if source:
                GLib.source_remove(source)
        self.heartbeat = self.deadline = 0
        self._token = object()
        process, self.process = self.process, None
        connection, self.connection = self.connection, None
        self.output_stream = None
        self.input = None
        self.unlocked = False
        self.is_daemon = False
        self.writing = False
        if process:
            try:
                process.get_stdin_pipe().close(None)
            except GLib.Error:
                pass
        if connection:
            try:
                connection.close(None)
            except GLib.Error:
                pass
        self.changed()
