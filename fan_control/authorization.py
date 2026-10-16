"""Daemon socket client for fan and thermal profile control."""

import json
from pathlib import Path

from gi.repository import Gio, GLib

from .hardware import PROFILES
from .service import DAEMON_SOCKET


class ServiceUnavailable(ValueError):
    """Raised when the background system service is not reachable."""
    pass


class AuthorizationSession:
    """Client for the background fan control system service daemon."""

    def __init__(self, changed=lambda: None, reply_timeout_ms=5000,
                 socket_path: Path | None = DAEMON_SOCKET):
        self.changed = changed
        self.reply_timeout_ms = reply_timeout_ms
        self.socket_path = Path(socket_path) if socket_path is not None else None
        self.connection = None
        self.input = None
        self.output_stream = None
        self.unlocked = False
        self.pending = None
        self.counter = 0
        self.deadline = 0
        self.writing = False
        self._token = object()
        if self.socket_path and self.socket_path.exists():
            self._connect()

    @property
    def is_daemon(self):
        return self.unlocked

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
        if self.connection is not None:
            return
        if self.socket_path and self.socket_path.exists():
            self._connect()
            return
        self._fail(ServiceUnavailable("The fan-control background service is not running."))

    def _connect(self):
        if not self.socket_path:
            return
        client = Gio.SocketClient.new()
        address = Gio.UnixSocketAddress.new(str(self.socket_path))
        token = object()
        self._token = token
        try:
            client.connect_async(address, None, self._on_connected, token)
        except (GLib.Error, OSError) as error:
            self.connection = None
            self.unlocked = False
            if self.pending:
                self._fail(ServiceUnavailable(f"Cannot connect to background service: {error}"))

    def _on_connected(self, client, result, token):
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
            self._read(self.connection)
        except (GLib.Error, OSError) as error:
            self.connection = None
            self.unlocked = False
            if self.pending:
                self._fail(ServiceUnavailable(f"Cannot connect to background service: {error}"))

    def _read(self, connection):
        if self.input:
            self.input.read_line_async(GLib.PRIORITY_DEFAULT, None, self._received, connection)

    def _received(self, stream, result, connection):
        try:
            line, _ = stream.read_line_finish_utf8(result)
            if connection is not self.connection:
                return
            if line is None:
                self._fail(ServiceUnavailable("The fan-control background service disconnected."))
                return
            message = json.loads(line)
            if not self.unlocked:
                if message != {"ready": True}:
                    raise ValueError("The fan-control service protocol did not start correctly.")
                self.unlocked = True
                self.changed()
                self._send_change()
            else:
                if (not self.pending or type(message) is not dict
                        or message.get("id") != self.pending[0]["id"]
                        or type(message.get("ok")) is not bool):
                    raise ValueError("The fan-control service returned an invalid response.")
                error = None if message["ok"] else ValueError(str(message.get("error", "The firmware refused the setting.")))
                self._finish(error)
            if connection is self.connection:
                self._read(connection)
        except (GLib.Error, ValueError, TypeError) as error:
            if connection is self.connection:
                self._fail(ValueError(str(error)))

    def _send_change(self):
        if self.pending is None:
            return
        self.deadline = GLib.timeout_add(self.reply_timeout_ms, self._timed_out)
        self._write(self.pending[0])

    def _write(self, message):
        connection = self.connection
        if self.writing:
            GLib.timeout_add(10, self._write_when_ready, message, connection)
            return
        self.writing = True
        stream = self.output_stream
        if stream:
            stream.write_all_async(
                (json.dumps(message) + "\n").encode(), GLib.PRIORITY_DEFAULT, None, self._written, connection)

    def _write_when_ready(self, message, connection):
        if connection is not self.connection:
            return GLib.SOURCE_REMOVE
        if self.writing:
            return GLib.SOURCE_CONTINUE
        self._write(message)
        return GLib.SOURCE_REMOVE

    def _written(self, stream, result, connection):
        error = None
        try:
            stream.write_all_finish(result)
        except GLib.Error as failure:
            error = failure
        if connection is not self.connection:
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

    def _timed_out(self):
        self.deadline = 0
        self._fail(ValueError("Timed out changing the fan setting. Check hardware state before retrying."))
        return GLib.SOURCE_REMOVE

    def _fail(self, error):
        self.close()
        self._finish(error)

    def close(self):
        if self.deadline:
            GLib.source_remove(self.deadline)
            self.deadline = 0
        self._token = object()
        connection, self.connection = self.connection, None
        self.output_stream = None
        self.input = None
        self.unlocked = False
        self.writing = False
        if connection:
            try:
                connection.close(None)
            except GLib.Error:
                pass
        self.changed()
