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

from fan_control.authorization import AuthorizationSession, AuthenticationCancelled, session_argv
from fan_control.hardware import WriteRequest
import test_hardware
from session_fixture import fixture_argv, ROOT
from fan_control.native import host_helper_path


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        fixture = test_hardware.HardwareTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.launches = []

        def argv():
            self.launches.append(True)
            return fixture_argv(fixture.root)
        self.session = AuthorizationSession(argv_factory=argv, socket_path=None)
        self.addCleanup(self.session.close)

    def change(self, value, path="platform_profile"):
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
        self.session.change(WriteRequest(Path('/client-supplied-path-is-ignored') / path, value), done)
        if not results:
            loop.run()
        if not expired:
            GLib.source_remove(timer)
        self.assertFalse(expired, "Session did not complete the request")
        self.assertEqual(len(results), 1)
        return results[0]

    def spin(self, milliseconds):
        loop = GLib.MainLoop()
        GLib.timeout_add(milliseconds, lambda: (loop.quit(), GLib.SOURCE_REMOVE)[1])
        loop.run()

    def test_one_authorization_covers_profiles_max_and_auto_then_lock_reauthenticates(self):
        self.assertIsNone(self.change("quiet"))
        self.assertIsNone(self.change("0", "pwm1_enable"))
        self.assertIsNone(self.change("2", "pwm1_enable"))
        self.assertEqual(len(self.launches), 1)
        self.assertTrue(self.session.unlocked)
        self.assertEqual(self.fixture.hardware.read().profile, "quiet")
        self.assertEqual(self.fixture.hardware.read().mode, 2)
        process = self.session.process
        self.session.close()
        process.wait(None)
        self.assertTrue(process.get_successful())
        self.assertFalse(self.session.unlocked)
        self.assertIsNone(self.change("balanced"))
        self.assertEqual(len(self.launches), 2)

    def test_cancelled_authentication_can_be_retried_without_a_write(self):
        real_factory = self.session.argv_factory
        self.session.argv_factory = lambda: [sys.executable, "-I", "-c", "raise SystemExit(126)"]
        self.assertIsInstance(self.change("quiet"), AuthenticationCancelled)
        self.assertEqual(self.fixture.hardware.read().profile, "balanced")
        self.assertFalse(self.session.unlocked)
        self.session.argv_factory = real_factory
        self.assertIsNone(self.change("quiet"))

    def test_firmware_rejection_does_not_reprompt_or_drop_the_session(self):
        self.fixture.acpi.joinpath("platform_profile_choices").write_text("quiet balanced")
        self.assertIn("not supported", str(self.change("performance")))
        self.assertTrue(self.session.unlocked)
        self.assertIsNone(self.change("quiet"))
        self.assertEqual(len(self.launches), 1)

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
        self.assertEqual(self.fixture.hardware.read().profile, "balanced")
        self.assertEqual(self.fixture.hardware.read().mode, 2)

    def test_heartbeat_preserves_session_and_missing_heartbeat_expires_it(self):
        self.session.argv_factory = lambda: fixture_argv(self.fixture.root, idle_seconds=.2)
        self.session.heartbeat_ms = 30
        self.assertIsNone(self.change("quiet"))
        self.spin(450)
        self.assertTrue(self.session.unlocked)
        self.assertIsNone(self.change("0", "pwm1_enable"))
        GLib.source_remove(self.session.heartbeat)
        self.session.heartbeat = 0
        self.spin(350)
        self.assertFalse(self.session.unlocked)
        self.assertIsNone(self.session.process)

    def test_unanswered_request_locks_without_replaying_a_write(self):
        self.session.reply_timeout_ms = 60
        self.session.argv_factory = lambda: [sys.executable, "-I", "-u", "-c",
                                             "import sys; print('{\"ready\":true}', flush=True); list(sys.stdin)"]
        self.assertIn("Timed out", str(self.change("quiet")))
        self.assertFalse(self.session.unlocked)
        self.assertEqual(self.fixture.hardware.read().profile, "balanced")

    def test_crashed_session_fails_pending_request_and_next_click_can_retry(self):
        self.session.argv_factory = lambda: [sys.executable, "-I", "-u", "-c",
                                             "import sys; print('{\"ready\":true}', flush=True); sys.stdin.readline(); sys.exit(1)"]
        self.assertIn("session ended", str(self.change("quiet")))
        self.session.argv_factory = lambda: fixture_argv(self.fixture.root)
        self.assertIsNone(self.change("quiet"))

    def test_closing_during_a_heartbeat_write_closes_the_pipe_after_completion(self):
        self.assertIsNone(self.change("quiet"))
        process = self.session.process
        self.session._ping()
        self.session.close()
        self.spin(100)
        process.wait(None)
        self.assertTrue(process.get_successful())
        self.assertFalse(self.session.unlocked)

    def test_protocol_recovers_from_invalid_json_and_rejects_oversized_frames(self):
        valid = json.dumps({"id": 1, "operation": "profile", "value": "quiet"})
        result = subprocess.run(fixture_argv(self.fixture.root), input="not-json\n" + valid + "\n", text=True, capture_output=True, check=True)
        messages = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(messages[0], {"ready": True})
        self.assertIsNone(messages[1]["id"])
        self.assertFalse(messages[1]["ok"])
        self.assertEqual(messages[2], {"id": 1, "ok": True})
        self.assertEqual(self.fixture.hardware.read().profile, "quiet")
        subprocess.run(fixture_argv(self.fixture.root), input="x" * 2048 + "\n", text=True, capture_output=True, check=True)
        self.assertEqual(self.fixture.hardware.read().profile, "quiet")

    def test_root_entry_point_refuses_unprivileged_execution(self):
        result = subprocess.run([str(ROOT / "build/native/victus-fan-control-helper"), "--session"],
                                input="", text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Administrator authentication", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_flatpak_uses_the_pinned_host_deployment_without_interpreters(self):
        with patch.object(Path, "exists", return_value=True), patch.object(Path, "read_text", return_value="[Instance]\napp-path=/host/app files\n"):
            argv = session_argv()
        self.assertEqual(argv, ["/usr/bin/flatpak-spawn", "--host", "--watch-bus", "/usr/bin/pkexec", "--disable-internal-agent",
                                "/host/app files/libexec/victus-fan-control-helper", "--session"])

    def test_invalid_flatpak_deployment_paths_are_rejected(self):
        for path in ("", "relative", "/host/../other"):
            with patch.object(Path, "exists", return_value=True), patch.object(Path, "read_text", return_value=f"[Instance]\napp-path={path}\n"):
                with self.assertRaises(ValueError):
                    host_helper_path()

    def test_daemon_socket_connection_and_request(self):
        sock_dir = tempfile.mkdtemp()
        sock_path = Path(sock_dir) / "test-daemon.sock"
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(sock_path))
        srv.listen(1)

        def handle():
            conn, _ = srv.accept()
            conn.sendall(b'{"ready": true}\n')
            data = conn.recv(1024)
            msg = json.loads(data.decode().strip())
            reply = {"id": msg["id"], "ok": True}
            conn.sendall((json.dumps(reply) + "\n").encode())
            srv.close()

        t = threading.Thread(target=handle)
        t.start()

        session = AuthorizationSession(argv_factory=lambda: self.launches.append(True), socket_path=sock_path)
        self.addCleanup(session.close)
        self.spin(100)
        self.assertTrue(session.unlocked)
        self.assertTrue(session.is_daemon)

        loop = GLib.MainLoop()
        results = []
        session.change(WriteRequest(Path("/sys/test/platform_profile"), "quiet"), lambda err: (results.append(err), loop.quit()))
        loop.run()
        t.join()
        if sock_path.exists():
            os.remove(sock_path)
        os.rmdir(sock_dir)

        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0])
        self.assertEqual(len(self.launches), 0)

    def test_daemon_socket_fallback_when_socket_missing(self):
        fake_path = Path("/tmp/definitely-nonexistent-victus-123.sock")
        session = AuthorizationSession(argv_factory=lambda: fixture_argv(self.fixture.root), socket_path=fake_path)
        self.addCleanup(session.close)
        self.assertFalse(session.unlocked)
        self.assertFalse(session.is_daemon)

        loop = GLib.MainLoop()
        results = []
        session.change(WriteRequest(Path("/sys/test/platform_profile"), "quiet"), lambda err: (results.append(err), loop.quit()))
        loop.run()

        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0])
        self.assertTrue(session.unlocked)
        self.assertFalse(session.is_daemon)

    def test_daemon_socket_fallback_when_connection_fails(self):
        sock_dir = tempfile.mkdtemp()
        sock_path = Path(sock_dir) / "dead.sock"
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(sock_path))
        srv.close()  # socket file exists on disk, but no listener

        session = AuthorizationSession(argv_factory=lambda: fixture_argv(self.fixture.root), socket_path=sock_path)
        self.addCleanup(session.close)

        loop = GLib.MainLoop()
        results = []
        session.change(WriteRequest(Path("/sys/test/platform_profile"), "quiet"), lambda err: (results.append(err), loop.quit()))
        loop.run()
        if sock_path.exists():
            os.remove(sock_path)
        os.rmdir(sock_dir)

        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0])
        self.assertTrue(session.unlocked)
        self.assertFalse(session.is_daemon)


if __name__ == "__main__":
    unittest.main()
