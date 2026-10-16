import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from gi.repository import GLib

from fan_control.authorization import AuthorizationSession, ServiceUnavailable
from fan_control.hardware import WriteRequest
import test_hardware
from session_fixture import fixture_argv, fixture_session, ROOT
from fan_control.native import host_helper_path


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        fixture = test_hardware.HardwareTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture

    def spin(self, milliseconds):
        loop = GLib.MainLoop()
        GLib.timeout_add(milliseconds, lambda: (loop.quit(), GLib.SOURCE_REMOVE)[1])
        loop.run()

    def change_with_session(self, session, value, path="platform_profile"):
        loop = GLib.MainLoop()
        results = []
        expired = []
        def timeout():
            expired.append(True)
            loop.quit()
            return GLib.SOURCE_REMOVE
        timer = GLib.timeout_add(2500, timeout)
        def done(error):
            results.append(error)
            loop.quit()
        session.change(WriteRequest(Path('/client-supplied-path-is-ignored') / path, value), done)
        if not results:
            loop.run()
        if not expired:
            GLib.source_remove(timer)
        self.assertFalse(expired, "Session did not complete the request")
        self.assertEqual(len(results), 1)
        return results[0]

    def test_daemon_socket_connection_and_requests(self):
        sock_dir = tempfile.mkdtemp()
        sock_path = Path(sock_dir) / "test-daemon.sock"
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(sock_path))
        srv.listen(1)

        def handle():
            conn, _ = srv.accept()
            conn.sendall(b'{"ready": true}\n')
            for _ in range(3):
                data = conn.recv(1024)
                if not data:
                    break
                msg = json.loads(data.decode().strip())
                reply = {"id": msg["id"], "ok": True}
                conn.sendall((json.dumps(reply) + "\n").encode())
            conn.close()
            srv.close()

        t = threading.Thread(target=handle)
        t.start()

        session = AuthorizationSession(socket_path=sock_path)
        self.addCleanup(session.close)
        self.spin(100)
        self.assertTrue(session.unlocked)

        self.assertIsNone(self.change_with_session(session, "quiet"))
        self.assertIsNone(self.change_with_session(session, "0", "pwm1_enable"))
        self.assertIsNone(self.change_with_session(session, "2", "pwm1_enable"))
        self.assertTrue(session.unlocked)

        session.close()
        t.join()
        if sock_path.exists():
            os.remove(sock_path)
        os.rmdir(sock_dir)

    def test_daemon_socket_missing_fails_with_service_unavailable(self):
        fake_path = Path("/tmp/definitely-nonexistent-victus-123.sock")
        session = AuthorizationSession(socket_path=fake_path)
        self.addCleanup(session.close)
        self.assertFalse(session.unlocked)

        err = self.change_with_session(session, "quiet")
        self.assertIsInstance(err, ServiceUnavailable)
        self.assertIn("not running", str(err))

    def test_real_fixture_daemon_writes_and_reconnects(self):
        launched = []
        session = fixture_session(self.fixture.root, launched)
        self.addCleanup(session.fixture_daemon.close)
        self.addCleanup(session.close)
        # Exercise the constructor's in-flight connect without a preparatory spin.
        self.assertIsNone(self.change_with_session(session, "quiet"))
        self.assertEqual(self.fixture.hardware.read().profile, "quiet")
        session.close()
        self.assertIsNone(self.change_with_session(session, "0", "pwm1_enable"))
        self.assertEqual(self.fixture.hardware.read().mode, 0)
        self.assertEqual(launched, [True])

    def test_silent_daemon_greeting_times_out_and_close_completes_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "silent.sock"
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                server.bind(str(path))
                server.listen(2)
                session = AuthorizationSession(socket_path=path, reply_timeout_ms=50)
                self.addCleanup(session.close)
                # A listening socket accepts connections but never sends its greeting.
                error = self.change_with_session(session, "quiet")
                self.assertIn("Timed out", str(error))
                self.assertFalse(session.unlocked)
                self.assertIsNone(session.pending)
                self.assertIsNone(session.connection)

                session.connect()
                results = []
                session.change(WriteRequest(Path("platform_profile"), "quiet"), results.append)
                session.close()
                self.spin(20)
                self.assertEqual(len(results), 1)
                self.assertIsInstance(results[0], ServiceUnavailable)
                self.assertIsNone(session.pending)

    def test_daemon_socket_connection_refused_fails_with_service_unavailable(self):
        sock_dir = tempfile.mkdtemp()
        sock_path = Path(sock_dir) / "dead.sock"
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(sock_path))
        srv.close()

        session = AuthorizationSession(socket_path=sock_path)
        self.addCleanup(session.close)

        err = self.change_with_session(session, "quiet")
        if sock_path.exists():
            os.remove(sock_path)
        os.rmdir(sock_dir)

        self.assertIsInstance(err, ServiceUnavailable)

    def test_daemon_socket_disconnect_marks_session_locked(self):
        sock_dir = tempfile.mkdtemp()
        sock_path = Path(sock_dir) / "disconnect.sock"
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(sock_path))
        srv.listen(1)

        def handle():
            conn, _ = srv.accept()
            conn.sendall(b'{"ready": true}\n')
            # Wait for client to establish session before disconnecting
            ready_event.wait(1.0)
            conn.close()
            srv.close()

        ready_event = threading.Event()
        t = threading.Thread(target=handle)
        t.start()

        session = AuthorizationSession(socket_path=sock_path)
        self.addCleanup(session.close)
        self.spin(100)
        self.assertTrue(session.unlocked)
        ready_event.set()

        # Allow time to detect remote EOF
        self.spin(100)
        self.assertFalse(session.unlocked)
        t.join()
        if sock_path.exists():
            os.remove(sock_path)
        os.rmdir(sock_dir)

    def test_daemon_socket_timeout_fails_request(self):
        sock_dir = tempfile.mkdtemp()
        sock_path = Path(sock_dir) / "timeout.sock"
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(sock_path))
        srv.listen(1)

        def handle():
            conn, _ = srv.accept()
            conn.sendall(b'{"ready": true}\n')
            _ = conn.recv(1024)
            # Never replies
            self.spin(200)
            conn.close()
            srv.close()

        t = threading.Thread(target=handle)
        t.start()

        session = AuthorizationSession(socket_path=sock_path, reply_timeout_ms=50)
        self.addCleanup(session.close)
        self.spin(100)
        self.assertTrue(session.unlocked)

        err = self.change_with_session(session, "quiet")
        self.assertIn("Timed out", str(err))
        t.join()
        if sock_path.exists():
            os.remove(sock_path)
        os.rmdir(sock_dir)

    def test_firmware_rejection_reports_error(self):
        sock_dir = tempfile.mkdtemp()
        sock_path = Path(sock_dir) / "rejection.sock"
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(sock_path))
        srv.listen(1)

        def handle():
            conn, _ = srv.accept()
            conn.sendall(b'{"ready": true}\n')
            data = conn.recv(1024)
            msg = json.loads(data.decode().strip())
            reply = {"id": msg["id"], "ok": False, "error": "Setting not supported by firmware."}
            conn.sendall((json.dumps(reply) + "\n").encode())
            conn.close()
            srv.close()

        t = threading.Thread(target=handle)
        t.start()

        session = AuthorizationSession(socket_path=sock_path)
        self.addCleanup(session.close)
        self.spin(100)
        self.assertTrue(session.unlocked)

        err = self.change_with_session(session, "performance")
        self.assertIn("not supported by firmware", str(err))
        t.join()
        if sock_path.exists():
            os.remove(sock_path)
        os.rmdir(sock_dir)

    def test_server_rejects_unknown_operations_values_and_client_paths(self):
        cases = [[], {"operation": "shell", "value": "id", "id": 1},
                 {"operation": "profile", "value": "quiet\nperformance", "id": 1},
                 {"operation": "fan", "value": "1", "id": 1},
                 {"operation": "fan", "value": 0, "id": 1},
                 {"operation": "profile", "value": "quiet", "id": True},
                 {"operation": "profile", "value": "quiet", "id": 1, "path": "/etc/passwd"}]
        payload = "".join(json.dumps(case) + "\n" for case in cases)
        result = subprocess.run(fixture_argv(self.fixture.root), input=payload, text=True, capture_output=True, check=True)
        messages = [json.loads(line) for line in result.stdout.splitlines()][1:]
        self.assertEqual(len(messages), len(cases))
        self.assertTrue(all(not message["ok"] for message in messages))

    def test_root_entry_point_refuses_unprivileged_execution(self):
        result = subprocess.run([str(ROOT / "build/native/victus-fan-control-helper"), "--daemon"],
                                input="", text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Administrator authentication", result.stderr)

    def test_flatpak_deployment_path_resolution(self):
        with patch.object(Path, "exists", return_value=True), patch.object(Path, "read_text", return_value="[Instance]\napp-path=/host/app files\n"):
            helper = host_helper_path()
        self.assertEqual(helper, Path("/host/app files/libexec/victus-fan-control-helper"))

    def test_invalid_flatpak_deployment_paths_are_rejected(self):
        for path in ("", "relative", "/host/../other"):
            with patch.object(Path, "exists", return_value=True), patch.object(Path, "read_text", return_value=f"[Instance]\napp-path={path}\n"):
                with self.assertRaises(ValueError):
                    host_helper_path()


if __name__ == "__main__":
    unittest.main()
