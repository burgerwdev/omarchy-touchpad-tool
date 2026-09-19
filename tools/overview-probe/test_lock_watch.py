"""Synthetic Wayland stream tests only; never connect to the live compositor."""

import importlib.util
import os
from pathlib import Path
import socket
import struct
import threading
import time
import unittest
from unittest import mock


SPEC = importlib.util.spec_from_file_location(
    "lock_watch", Path(__file__).resolve().parents[2] / "overview" / "lock-watch.py"
)
watcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watcher)


def u32(value):
    return struct.pack("=I", value)


def event(object_id, opcode, payload=b""):
    return struct.pack("=II", object_id, ((len(payload) + 8) << 16) | opcode) + payload


def wl_string(value):
    raw = value.encode() + b"\0"
    return u32(len(raw)) + raw + b"\0" * (-len(raw) % 4)


def exact(connection, length):
    result = b""
    while len(result) < length:
        piece = connection.recv(length - len(result))
        if not piece:
            raise AssertionError("client disconnected before expected request")
        result += piece
    return result


def request(connection):
    header = exact(connection, 8)
    object_id, word = struct.unpack("=II", header)
    return object_id, word & 0xFFFF, exact(connection, (word >> 16) - 8)


class LockWatchTests(unittest.TestCase):
    def test_main_plain_output_and_consumer_pipe_contract(self):
        for exit_on_close in (False, True):
            with self.subTest(exit_on_close=exit_on_close):
                reader, writer = os.pipe()
                with os.fdopen(reader) as output, os.fdopen(writer, "w") as stdout:
                    arguments = ["lock-watch.py", "--format", "plain", "--init-timeout", "0.25"]
                    if exit_on_close:
                        arguments.append("--exit-on-consumer-close")

                    def observe(emit, timeout, *, consumer_fd):
                        self.assertEqual(timeout, 0.25)
                        self.assertEqual(consumer_fd, stdout.fileno() if exit_on_close else None)
                        emit("unknown", "initializing")
                        emit("unlocked", "initial-sync")
                        return 0

                    with mock.patch.object(watcher.sys, "argv", arguments), \
                            mock.patch.object(watcher.sys, "stdout", stdout), \
                            mock.patch.object(watcher.signal, "signal") as register_signal, \
                            mock.patch.object(watcher, "watch", side_effect=observe) as observe_call:
                        self.assertEqual(watcher.main(), 0)
                        observe_call.assert_called_once()
                        register_signal.assert_called_once()
                        self.assertEqual(register_signal.call_args.args[0], watcher.signal.SIGTERM)
                    stdout.close()
                    self.assertEqual(output.read(), "unknown\nunlocked\n")

    def run_server(self, script, timeout=0.5):
        client, server = socket.socketpair()
        server.settimeout(2)
        emissions, errors = [], []

        def serve():
            with server:
                try:
                    script(server, emissions)
                except BaseException as error:
                    errors.append(error)

        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        status = watcher.watch(lambda state, reason: emissions.append((state, reason)), timeout, lambda _: client)
        worker.join(3)
        self.assertFalse(worker.is_alive(), "fake server did not finish")
        if errors:
            raise errors[0]
        return status, emissions

    def registry(self, connection, supported=True, fragment=False):
        self.assertEqual(request(connection), (1, 1, u32(2)))
        self.assertEqual(request(connection), (1, 0, u32(3)))
        data = event(2, 0, u32(10) + wl_string("wl_compositor") + u32(6))
        if supported:
            data += event(2, 0, u32(77) + wl_string("hyprland_lock_notifier_v1") + u32(1))
        data += event(3, 0, u32(0)) + event(1, 1, u32(3))
        if fragment:
            for byte in data:
                connection.sendall(bytes([byte]))
        else:
            connection.sendall(data)

    def bind(self, connection):
        self.assertEqual(request(connection), (2, 0, u32(77) + wl_string("hyprland_lock_notifier_v1") + u32(1) + u32(4)))
        self.assertEqual(request(connection), (4, 1, u32(5)))
        self.assertEqual(request(connection), (1, 0, u32(6)))

    def test_initial_unlocked_requires_second_sync_then_transitions(self):
        def script(connection, emissions):
            self.registry(connection, fragment=True)
            self.bind(connection)
            self.assertEqual([item[0] for item in emissions], ["unknown"])
            # Coalesced events must stay ordered, including callback deletion.
            connection.sendall(event(6, 0, u32(0)) + event(1, 1, u32(6)) + event(5, 0) + event(5, 1))

        status, emissions = self.run_server(script)
        self.assertEqual(status, 1)
        self.assertEqual([item[0] for item in emissions], ["unknown", "unlocked", "locked", "unlocked", "unknown"])
        self.assertEqual(emissions[1][1], "initial-sync")

    def test_initial_locked_never_briefly_emits_unlocked(self):
        def script(connection, _emissions):
            self.registry(connection)
            self.bind(connection)
            connection.sendall(event(5, 0) + event(6, 0, u32(0)))

        _, emissions = self.run_server(script)
        self.assertEqual([item[0] for item in emissions], ["unknown", "locked", "unknown"])

    def test_unsupported_registry_fails_closed(self):
        status, emissions = self.run_server(lambda connection, _: self.registry(connection, supported=False))
        self.assertEqual(status, 1)
        self.assertEqual(emissions[-1], ("unknown", "lock notifier unsupported"))

    def test_no_initial_sync_stays_unknown_and_times_out(self):
        def script(connection, _emissions):
            self.registry(connection)
            self.bind(connection)
            self.assertEqual(connection.recv(1), b"")

        started = time.monotonic()
        status, emissions = self.run_server(script, timeout=0.05)
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(status, 1)
        self.assertEqual([item[0] for item in emissions], ["unknown", "unknown"])
        self.assertEqual(emissions[-1][1], "TimeoutError")

    def test_disconnect_mid_frame_fails_closed(self):
        _, emissions = self.run_server(lambda connection, _: connection.sendall(event(2, 0, u32(77))[:5]))
        self.assertEqual([item[0] for item in emissions], ["unknown", "unknown"])

    def test_malformed_header_fails_closed(self):
        for size in (0, 4, 9):
            with self.subTest(size=size):
                def script(connection, _emissions):
                    # Finish the client's initial writes before closing so this
                    # exercises malformed framing, not a send-side broken pipe.
                    self.assertEqual(request(connection), (1, 1, u32(2)))
                    self.assertEqual(request(connection), (1, 0, u32(3)))
                    connection.sendall(struct.pack("=II", 2, size << 16))

                status, emissions = self.run_server(script)
                self.assertEqual(status, 1)
                self.assertEqual(emissions[-1], ("unknown", "invalid event header"))

    def test_bad_lock_transitions_fail_closed(self):
        for events in (event(5, 1), event(5, 0) * 2, event(5, 2), event(5, 0, u32(1))):
            with self.subTest(events=events):
                def script(connection, _emissions):
                    self.registry(connection)
                    self.bind(connection)
                    connection.sendall(events)

                status, emissions = self.run_server(script)
                self.assertEqual(status, 1)
                self.assertEqual(emissions[-1][0], "unknown")
                self.assertNotIn("unlocked", [item[0] for item in emissions])

    def test_display_error_and_removed_notifier_invalidate_unlocked(self):
        for failure in (event(1, 0, u32(4) + u32(1) + wl_string("private diagnostic")), event(2, 1, u32(77))):
            with self.subTest(failure=failure):
                def script(connection, _emissions):
                    self.registry(connection)
                    self.bind(connection)
                    connection.sendall(event(6, 0, u32(0)) + failure)

                status, emissions = self.run_server(script)
                self.assertEqual(status, 1)
                self.assertEqual([item[0] for item in emissions], ["unknown", "unlocked", "unknown"])
                self.assertNotIn("private diagnostic", repr(emissions))

    def test_malformed_initial_callback_never_emits_unlocked(self):
        def script(connection, _emissions):
            self.registry(connection)
            self.bind(connection)
            connection.sendall(event(6, 0, u32(0) * 2))

        _, emissions = self.run_server(script)
        self.assertEqual([item[0] for item in emissions], ["unknown", "unknown"])

    def test_missing_session_environment_fails_closed_without_socket(self):
        emissions = []
        with mock.patch.dict(watcher.os.environ, {}, clear=True), mock.patch.object(watcher.socket, "socket") as factory:
            status = watcher.watch(lambda *item: emissions.append(item))
            factory.assert_not_called()
        self.assertEqual(status, 1)
        self.assertEqual(emissions[-1], ("unknown", "WAYLAND_DISPLAY is not set"))

    def test_absolute_and_relative_display_paths(self):
        for display, expected in (("wayland-test", "/run/test/wayland-test"), ("/tmp/wayland-test", "/tmp/wayland-test")):
            with self.subTest(display=display), mock.patch.dict(watcher.os.environ, {"WAYLAND_DISPLAY": display, "XDG_RUNTIME_DIR": "/run/test"}, clear=True), mock.patch.object(watcher.socket, "socket") as factory:
                watcher.connect_display(2)
                factory.return_value.connect.assert_called_once_with(expected)
                factory.return_value.settimeout.assert_called_once_with(2)

    def test_consumer_closure_exits_during_initialization_and_idle_watch(self):
        for initialized in (False, True):
            with self.subTest(initialized=initialized):
                client, server = socket.socketpair()
                reader, writer = os.pipe()
                server.settimeout(2)
                emissions, errors, results = [], [], []
                ready = threading.Event()

                def emit(state, reason):
                    emissions.append((state, reason))
                    if state == "unlocked":
                        ready.set()

                def run():
                    try:
                        results.append(watcher.watch(emit, timeout=5, connect=lambda _: client, consumer_fd=writer))
                    except BaseException as error:
                        errors.append(error)

                worker = threading.Thread(target=run, daemon=True)
                worker.start()
                try:
                    self.registry(server)
                    self.bind(server)
                    if initialized:
                        server.sendall(event(6, 0, u32(0)))
                        self.assertTrue(ready.wait(1))
                    # No more Wayland events; closing the owned pipe reader must
                    # wake the watcher without a heartbeat or final emission.
                    before_close = list(emissions)
                    os.close(reader)
                    reader = None
                    worker.join(1)
                    self.assertFalse(worker.is_alive(), "idle watcher survived consumer closure")
                    self.assertEqual(server.recv(1), b"")
                    self.assertEqual(errors, [])
                    self.assertEqual(results, [0])
                    self.assertEqual(emissions, before_close)
                finally:
                    if reader is not None:
                        os.close(reader)
                    os.close(writer)
                    server.close()
                    worker.join(1)


if __name__ == "__main__":
    unittest.main()
