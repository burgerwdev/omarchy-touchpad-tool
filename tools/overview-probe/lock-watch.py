#!/usr/bin/env python3
"""Observe compositor lock state; never enumerate windows or change desktop state.

Run: python tools/overview-probe/lock-watch.py [--format plain]
JSON lines (default) contain state and reason. Only state=unlocked is permissive;
unknown, stream EOF, and process death must suppress a consumer's preview UI.
No retry/reconnect: failures emit unknown and exit 1. Initialization takes at
most --init-timeout seconds; a connected, idle compositor has no timeout.
Use --exit-on-consumer-close when stdout is a pipe to stop silently when its
reader disappears, even while no compositor events arrive.

Wire/ordering references (checked 2026-09-14):
https://github.com/hyprwm/hyprland-protocols/blob/main/protocols/hyprland-lock-notify-v1.xml
https://github.com/hyprwm/Hyprland/blob/efb50993780079460b0cbed1363e2166a2de1d9f/src/protocols/LockNotify.cpp
https://github.com/wayland-mirror/wayland/blob/main/protocol/wayland.xml

The notification sends locked immediately if already locked. A sync after
creating it establishes initial unlocked when no locked event preceded done.
The protocol reports completed transitions, not the beginning of a lock request.
This observer is prototype evidence, not a security boundary or capture gate.
"""

import argparse
import json
import math
import os
import select
import signal
import socket
import stat
import struct
import sys
import time


INTERFACE = "hyprland_lock_notifier_v1"
U32 = struct.Struct("=I")  # Wayland uses host byte order, 32-bit aligned fields.
HEADER = struct.Struct("=II")
DISPLAY, REGISTRY, REGISTRY_SYNC, MANAGER, NOTIFICATION, INITIAL_SYNC = range(1, 7)


class ProtocolError(Exception):
    pass


class ConsumerClosed(Exception):
    pass


def uint(value):
    return U32.pack(value)


def string(value):
    data = value.encode("utf-8") + b"\0"
    return uint(len(data)) + data + b"\0" * (-len(data) % 4)


def message(object_id, opcode, payload=b""):
    return HEADER.pack(object_id, ((len(payload) + 8) << 16) | opcode) + payload


class Arguments:
    def __init__(self, data):
        self.data = data
        self.offset = 0

    def uint(self):
        if self.offset + 4 > len(self.data):
            raise ProtocolError("truncated argument")
        value = U32.unpack_from(self.data, self.offset)[0]
        self.offset += 4
        return value

    def string(self):
        size = self.uint()
        end = self.offset + size
        padded_end = self.offset + ((size + 3) & ~3)
        if size == 0 or padded_end > len(self.data) or self.data[end - 1] != 0:
            raise ProtocolError("invalid string")
        value = self.data[self.offset:end - 1].decode("utf-8")
        self.offset = padded_end
        return value

    def finish(self):
        if self.offset != len(self.data):
            raise ProtocolError("unexpected arguments")


class Client:
    def __init__(self, connection, emit, deadline, consumer_fd=None):
        self.connection = connection
        self.emit = emit
        self.deadline = deadline
        self.buffer = bytearray()
        self.global_name = None
        self.registry_done = False
        self.ready = False
        self.locked = False
        self.state = "unknown"
        self.consumer_fd = consumer_fd
        self.poller = None
        if consumer_fd is not None:
            self.poller = select.poll()
            self.poller.register(connection, select.POLLIN)
            # ERR/HUP are returned even with an empty requested event mask.
            # Do not request POLLOUT: a writable pipe would create a busy loop.
            self.poller.register(consumer_fd, 0)

    def poll(self, timeout):
        events = self.poller.poll(timeout)
        if any(fd == self.consumer_fd and flags & (select.POLLERR | select.POLLHUP | select.POLLNVAL)
               for fd, flags in events):
            raise ConsumerClosed
        return events

    def set_state(self, state, reason):
        if state != self.state:
            self.state = state
            self.emit(state, reason)

    def set_timeout(self):
        if self.ready:
            self.connection.settimeout(None)
        else:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("initialization timeout")
            self.connection.settimeout(remaining)

    def send(self, object_id, opcode, payload):
        self.set_timeout()
        if self.poller is not None:
            self.poll(0)
        self.connection.sendall(message(object_id, opcode, payload))

    def receive(self):
        while True:
            self.set_timeout()
            if self.poller is not None:
                self.poll(0)
            if len(self.buffer) >= 8:
                object_id, word = HEADER.unpack_from(self.buffer)
                size, opcode = word >> 16, word & 0xFFFF
                if object_id == 0 or size < 8 or size % 4:
                    raise ProtocolError("invalid event header")
                if len(self.buffer) >= size:
                    payload = bytes(self.buffer[8:size])
                    del self.buffer[:size]
                    return object_id, opcode, Arguments(payload)
            if self.poller is not None:
                timeout = None if self.ready else max(0, math.ceil((self.deadline - time.monotonic()) * 1000))
                if not self.poll(timeout):
                    raise TimeoutError("initialization timeout")
            data = self.connection.recv(4096)
            if not data:
                raise ConnectionError("compositor disconnected")
            self.buffer.extend(data)

    def dispatch(self, object_id, opcode, args):
        if object_id == DISPLAY:
            if opcode == 0:
                args.uint()  # failing object
                args.uint()  # protocol error code
                args.string()  # don't expose compositor-provided text
                args.finish()
                raise ProtocolError("compositor protocol error")
            if opcode != 1 or args.uint() not in (REGISTRY_SYNC, INITIAL_SYNC):
                raise ProtocolError("unexpected display event")
        elif object_id == REGISTRY:
            name = args.uint()
            if opcode == 0:
                interface, version = args.string(), args.uint()
                if interface == INTERFACE and version >= 1:
                    self.global_name = name
            elif opcode == 1:
                if name == self.global_name:
                    raise ProtocolError("lock notifier removed")
            else:
                raise ProtocolError("unexpected registry event")
        elif object_id == REGISTRY_SYNC and not self.registry_done:
            if opcode != 0:
                raise ProtocolError("unexpected sync event")
            args.uint()
            args.finish()
            self.registry_done = True
            if self.global_name is None:
                raise ProtocolError("lock notifier unsupported")
            self.send(REGISTRY, 0, uint(self.global_name) + string(INTERFACE) + uint(1) + uint(MANAGER))
            self.send(MANAGER, 1, uint(NOTIFICATION))
            self.send(DISPLAY, 0, uint(INITIAL_SYNC))
        elif object_id == INITIAL_SYNC and self.registry_done and not self.ready:
            if opcode != 0:
                raise ProtocolError("unexpected sync event")
            args.uint()
            args.finish()
            self.ready = True
            self.set_state("locked" if self.locked else "unlocked", "initial-sync")
        elif object_id == NOTIFICATION and self.registry_done:
            args.finish()
            if opcode not in (0, 1) or (opcode == 0) == self.locked:
                raise ProtocolError("invalid lock transition")
            self.locked = opcode == 0
            self.set_state("locked" if self.locked else "unlocked", "notification")
        else:
            raise ProtocolError("unexpected event object")
        args.finish()

    def run(self):
        self.send(DISPLAY, 1, uint(REGISTRY))
        self.send(DISPLAY, 0, uint(REGISTRY_SYNC))
        while True:
            self.dispatch(*self.receive())


def connect_display(timeout):
    display = os.environ.get("WAYLAND_DISPLAY")
    if not display:
        raise ProtocolError("WAYLAND_DISPLAY is not set")
    if not os.path.isabs(display):
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        if not runtime or not os.path.isabs(runtime):
            raise ProtocolError("XDG_RUNTIME_DIR must be absolute")
        display = os.path.join(runtime, display)
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        connection.settimeout(timeout)
        connection.connect(display)
        return connection
    except BaseException:
        connection.close()
        raise


def watch(emit, timeout=3.0, connect=connect_display, consumer_fd=None):
    """Emit unknown before connecting; all connection/protocol failures exit 1."""
    emit("unknown", "initializing")
    deadline = time.monotonic() + timeout
    try:
        with connect(timeout) as connection:
            Client(connection, emit, deadline, consumer_fd).run()
    except ConsumerClosed:
        return 0
    except KeyboardInterrupt:
        emit("unknown", "stopped")
        return 0
    except (OSError, ConnectionError, ProtocolError, UnicodeError) as error:
        reason = str(error) if isinstance(error, ProtocolError) else type(error).__name__
        emit("unknown", reason)
        return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("json", "plain"), default="json")
    parser.add_argument("--init-timeout", type=float, default=3.0)
    parser.add_argument("--exit-on-consumer-close", action="store_true",
                        help="exit silently when the stdout pipe loses its reader")
    options = parser.parse_args()
    if not math.isfinite(options.init_timeout) or options.init_timeout <= 0:
        parser.error("--init-timeout must be finite and positive")

    def emit(state, reason):
        value = state if options.format == "plain" else json.dumps({"state": state, "reason": reason})
        print(value, flush=True)

    def stop(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    consumer_fd = None
    if options.exit_on_consumer_close and stat.S_ISFIFO(os.fstat(sys.stdout.fileno()).st_mode):
        consumer_fd = sys.stdout.fileno()
    try:
        return watch(emit, options.init_timeout, consumer_fd=consumer_fd)
    except BrokenPipeError:
        # A dead consumer needs no further state; avoid shutdown flush traceback.
        sys.stdout = open(os.devnull, "w")
        return 1


if __name__ == "__main__":
    sys.exit(main())
