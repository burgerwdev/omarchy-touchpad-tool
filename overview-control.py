#!/usr/bin/env python3
"""Control only Trackpad Plus's optional overview in this compositor session.

No command modifies trackpad settings, gestures, autostart, or the bar. Ordinary
status/close/stop never start the companion. All subprocess arguments are arrays.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import secrets
import select
import selectors
import shutil
import signal
import subprocess
import sys
import time

from trackpads import atomic_write, check_file, read_state_file, state_directory

PROTOCOL = 1
OPERATIONS = ('start', 'open', 'close', 'toggle', 'status', 'stop')
OUTPUT_LIMIT = 8192


class ControlError(Exception):
    """An actionable error containing no captured window data or raw IPC output."""


class Cancelled(ControlError):
    """A newer close withdrew this pending startup."""


def no_core():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def process_info(pid):
    """Read Linux process identity; start ticks distinguish reused PID numbers."""
    try:
        directory = Path('/proc') / str(pid)
        raw = (directory / 'stat').read_text()
        tail = raw[raw.rindex(')') + 2:].split()
        if tail[0] == 'Z':
            return None
        argv = (directory / 'cmdline').read_bytes().split(b'\0')[:-1]
        environment = {}
        for entry in (directory / 'environ').read_bytes().split(b'\0'):
            if b'=' in entry:
                key, value = entry.split(b'=', 1)
                if key.startswith(b'TRACKPAD_OVERVIEW_'):
                    environment[key.decode()] = value.decode()
        return {'start': tail[19], 'argv': [a.decode() for a in argv], 'env': environment,
                'uid': directory.stat().st_uid}
    except (FileNotFoundError, ProcessLookupError):
        return None
    except (PermissionError, UnicodeError, ValueError, IndexError) as exc:
        raise ControlError('Cannot verify overview process ownership; no process was controlled.') from exc


def bounded_command(argv, env, timeout):
    """Bound time and both output streams; never retain unbounded diagnostics."""
    process = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               preexec_fn=no_core)
    chunks = bytearray()
    total = 0
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, True)
            selector.register(process.stderr, selectors.EVENT_READ, False)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ControlError('Overview IPC timed out; retry or stop the companion.')
                for key, _ in selector.select(remaining):
                    block = os.read(key.fileobj.fileno(), 4096)
                    if not block:
                        selector.unregister(key.fileobj)
                        continue
                    total += len(block)
                    if total > OUTPUT_LIMIT:
                        raise ControlError('Overview IPC exceeded its output limit.')
                    if key.data:
                        chunks.extend(block)
        process.wait(timeout=max(0.001, deadline - time.monotonic()))
        if process.returncode:
            raise ControlError('Overview IPC is unavailable; retry or stop the companion.')
        try:
            result = json.loads(chunks)
        except (ValueError, UnicodeError) as exc:
            raise ControlError('Overview returned an invalid IPC response.') from exc
        if not isinstance(result, dict):
            raise ControlError('Overview returned an invalid IPC response.')
        return result
    except subprocess.TimeoutExpired as exc:
        raise ControlError('Overview IPC timed out; retry or stop the companion.') from exc
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()
        process.stderr.close()


class Controller:
    def __init__(self, base=None, runtime=None, session=None, qs=None, env=None, timeout=4.0):
        self.base = Path(base or Path(__file__).resolve().parent).resolve()
        self.config = str(self.base / 'overview' / 'shell.qml')
        self.env = dict(os.environ if env is None else env)
        self.runtime = Path(runtime or self.env.get('XDG_RUNTIME_DIR', ''))
        if not self.runtime.is_absolute():
            raise ControlError('XDG_RUNTIME_DIR is missing; run from your desktop session.')
        signature = self.env.get('HYPRLAND_INSTANCE_SIGNATURE', '')
        display = self.env.get('WAYLAND_DISPLAY', '')
        self.session = session if session is not None else signature + '|' + display
        if session is None and (not signature or not display):
            raise ControlError('No active Hyprland session was found.')
        if not self.session or len(self.session) > 1024:
            raise ControlError('The compositor session identity is invalid.')
        self.version = self.read_version()
        self.qs = qs or shutil.which('qs')
        self.timeout = timeout
        digest = hashlib.sha256(self.session.encode()).hexdigest()[:32]
        self.directory = self.runtime / ('trackpad-plus-overview-' + digest)
        self.record_path = self.directory / 'owner.json'
        self.lock_path = self.directory / 'control.lock'
        self.last_spawn = None
        self.last_spawn_token = None
        self.deadline = None
        self.open_generation = None
        self.generation_path = self.directory / 'close-generation'

    def read_version(self):
        try:
            value = json.loads((self.base / 'manifest.json').read_text())['version']
            if not isinstance(value, str) or not value or len(value) > 80:
                raise ValueError()
            return value
        except (OSError, ValueError, KeyError) as exc:
            raise ControlError('The Trackpad Plus manifest is missing or invalid; reinstall it.') from exc

    def missing(self):
        return {'ok': True, 'installed': Path(self.config).is_file() and bool(self.qs),
                'reachable': False, 'protocolCompatible': False, 'rendered': False,
                'opened': False, 'pending': False, 'result': 'not-running'}

    @contextmanager
    def locked(self, create, name='control.lock'):
        try:
            with state_directory(self.directory, create=create) as directory:
                info = os.fstat(directory)
                if info.st_uid != os.getuid() or info.st_mode & 0o077:
                    raise ControlError('Overview runtime directory must be private to this user.')
                fd = os.open(name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                             0o600, dir_fd=directory)
                try:
                    check_file(os.fstat(fd))
                    deadline = self.deadline or time.monotonic() + self.timeout
                    while True:
                        try:
                            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            break
                        except BlockingIOError:
                            if time.monotonic() >= deadline:
                                raise ControlError('Overview control is busy; retry shortly.')
                            time.sleep(0.02)
                    yield
                finally:
                    os.close(fd)
        except (ValueError, OSError) as exc:
            raise ControlError('Overview runtime ownership could not be verified.') from exc

    def remaining(self):
        if self.deadline is None:
            return self.timeout
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ControlError('Overview operation timed out; retry when ready.')
        return remaining

    def generation(self):
        value = read_state_file(self.generation_path)
        if value is None:
            return ''
        if len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ControlError('Overview close intent is invalid; no request was opened.')
        return value

    def cancelled(self):
        return self.open_generation is not None and self.generation() != self.open_generation

    def register_intent(self, operation):
        # This lock protects only a small atomic marker, never startup or IPC.
        # Register close before waiting for lifecycle work, so old flock waiters
        # and a slow startup can observe cancellation even if close waits too.
        with self.locked(operation in ('start', 'open', 'toggle'), 'intent.lock'):
            if operation in ('close', 'stop'):
                atomic_write(self.generation_path, secrets.token_hex(32))
            elif operation in ('start', 'open', 'toggle'):
                self.open_generation = self.generation()

    def record(self):
        try:
            raw = read_state_file(self.record_path)
            if raw is None:
                return None
            if len(raw) > OUTPUT_LIMIT:
                raise ValueError()
            data = json.loads(raw)
            if not isinstance(data, dict) or type(data.get('pid')) is not int or data['pid'] <= 1:
                raise ValueError()
            return data
        except (ValueError, OSError) as exc:
            raise ControlError('Overview ownership record is invalid; no process was controlled.') from exc

    def owns(self, record):
        start = record.get('start')
        token = record.get('token')
        if (not isinstance(start, str) or not start.isascii() or not start.isdigit()
                or not isinstance(token, str) or len(token) != 64
                or any(ch not in '0123456789abcdef' for ch in token)
                or any(not isinstance(record.get(key), str) or not record[key]
                       for key in ('config', 'session', 'version'))
                or not isinstance(record.get('argv'), list) or not record['argv']
                or any(not isinstance(arg, str) for arg in record['argv'])):
            raise ControlError('Overview ownership record is invalid; no process was controlled.')
        info = process_info(record['pid'])
        if info is None:
            return False
        # A different start time proves the saved process is gone. Discarding its
        # record is safe; never signal the unrelated process now using this PID.
        if info['start'] != start:
            return False
        argv = info['argv']
        env = info['env']
        try:
            config = argv[argv.index('-p') + 1]
        except (ValueError, IndexError):
            config = None
        valid = (info['uid'] == os.getuid() and info['start'] == record.get('start')
                 and config == self.config == record.get('config')
                 and isinstance(token, str) and len(token) == 64
                 and env.get('TRACKPAD_OVERVIEW_TOKEN') == token
                 and record.get('session') == self.session == env.get('TRACKPAD_OVERVIEW_SESSION')
                 and record.get('version') == env.get('TRACKPAD_OVERVIEW_VERSION')
                 and record.get('argv') == argv)
        if not valid:
            raise ControlError('Overview ownership does not match; no process was controlled.')
        return True

    def forget(self):
        # Caller holds the per-session lock; delete only this validated record.
        with state_directory(self.directory) as directory:
            try:
                os.unlink('owner.json', dir_fd=directory)
            except FileNotFoundError:
                pass

    def ipc(self, record, operation, timeout=None):
        if not self.qs:
            raise ControlError('Quickshell is missing; install it to use the overview.')
        argv = [self.qs, 'ipc', '--pid', str(record['pid']), 'call', 'trackpadOverview', operation]
        if operation != 'status':
            argv.append(record['token'])
        return bounded_command(argv, self.env, self.remaining() if timeout is None else timeout)

    def validate(self, record, reply):
        if (reply.get('protocol') != PROTOCOL or type(reply.get('pid')) is not int
                or reply.get('pid') != record['pid'] or reply.get('version') != self.version
                or reply.get('session') != self.session or reply.get('config') != self.config
                or not isinstance(reply.get('instance'), str) or not reply['instance']
                or len(reply['instance']) > 128
                or record.get('instance') not in (None, reply['instance'])):
            raise ControlError('Overview version or session handshake failed; stop it before upgrading.')
        for key in ('opened', 'pending', 'rendered'):
            if type(reply.get(key)) is not bool:
                raise ControlError('Overview returned an invalid lifecycle state.')
        if reply.get('lockState') not in ('unknown', 'locked', 'unlocked'):
            raise ControlError('Overview returned an invalid lock state.')
        # Allowlist output; never relay arbitrary IPC fields, diagnostics or titles.
        result = {key: reply[key] for key in ('protocol', 'version', 'session', 'pid', 'instance',
                                              'opened', 'pending', 'rendered', 'lockState')}
        result.update(ok=True, installed=True, reachable=True, protocolCompatible=True)
        if reply.get('result') in ('hidden', 'checking-lock', 'opened', 'locked', 'lock-unknown',
                                  'lock-unavailable', 'lock-timeout', 'closed', 'stopping', 'rendered',
                                  'workspace-changed', 'monitor-removed', 'no-monitor', 'selection', 'escape'):
            result['result'] = reply['result']
        if type(reply.get('mapped')) is bool:
            result['mapped'] = reply['mapped']
        for key in ('captures', 'ready', 'opens', 'closes'):
            if type(reply.get(key)) is int and 0 <= reply[key] <= 1000000:
                result[key] = reply[key]
        return result

    def stop_owned(self, record):
        if not self.owns(record):
            return
        # Pin the process before the second identity check; no PID-reuse signal race.
        try:
            descriptor = os.pidfd_open(record['pid'])
        except ProcessLookupError:
            return
        try:
            if not self.owns(record):
                return
            try:
                signal.pidfd_send_signal(descriptor, signal.SIGTERM)
                ready, _, _ = select.select([descriptor], [], [], min(self.timeout, 1.0))
                if not ready:
                    signal.pidfd_send_signal(descriptor, signal.SIGKILL)
                    ready, _, _ = select.select([descriptor], [], [], 1.0)
                    if not ready:
                        raise ControlError('Overview did not stop; its ownership record was retained. Retry stop.')
            except ProcessLookupError:
                pass
        finally:
            os.close(descriptor)
        if self.last_spawn is not None and self.last_spawn.pid == record['pid']:
            self.last_spawn.wait(timeout=1.0)

    def launch(self):
        if not self.qs or not Path(self.config).is_file():
            raise ControlError('The overview companion or Quickshell is missing; reinstall Trackpad Plus.')
        token = secrets.token_hex(32)
        environment = dict(self.env, QS_DISABLE_CRASH_HANDLER='1', TRACKPAD_OVERVIEW_TOKEN=token,
                           TRACKPAD_OVERVIEW_SESSION=self.session, TRACKPAD_OVERVIEW_VERSION=self.version)
        process = subprocess.Popen([self.qs, '-p', self.config], env=environment,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=True, preexec_fn=no_core)
        self.last_spawn = process
        self.last_spawn_token = token
        record = None
        try:
            info = process_info(process.pid)
            if info is None:
                raise ControlError('Overview exited during startup; check Quickshell dependencies.')
            record = {'pid': process.pid, 'start': info['start'], 'config': self.config,
                      'argv': info['argv'], 'token': token, 'session': self.session, 'version': self.version}
            atomic_write(self.record_path, json.dumps(record))
            deadline = self.deadline or time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                if self.cancelled():
                    raise Cancelled('Overview startup was cancelled by a newer close.')
                if process.poll() is not None:
                    raise ControlError('Overview exited during startup; check Quickshell dependencies.')
                try:
                    reply = self.ipc(record, 'status', max(0.001, deadline - time.monotonic()))
                except ControlError:
                    time.sleep(0.04)
                    continue
                self.validate(record, reply)
                record['instance'] = reply['instance']
                ready_info = process_info(process.pid)
                if ready_info is None or ready_info['start'] != record['start']:
                    raise ControlError('Overview exited during its readiness handshake.')
                record['argv'] = ready_info['argv']
                self.owns(record)
                atomic_write(self.record_path, json.dumps(record))
                return record, reply
            raise ControlError('Overview did not become ready before its startup deadline.')
        except BaseException:
            # Popen's child is ours; it is still unreaped, so its PID cannot be reused.
            if process.poll() is None:
                process.kill()
            process.wait()
            if record is not None:
                self.forget()
            raise

    def execute(self, operation):
        if operation not in OPERATIONS:
            raise ControlError('Unsupported overview operation.')
        self.deadline = time.monotonic() + self.timeout
        self.open_generation = None
        try:
            if operation not in ('start', 'open', 'toggle') and not self.directory.exists():
                return self.missing()
            if operation != 'status':
                self.register_intent(operation)
            return self.execute_locked(operation)
        except Cancelled:
            return self.missing()
        finally:
            self.deadline = None

    def execute_locked(self, operation):
        create = operation in ('start', 'open', 'toggle')
        if not create and not self.directory.exists():
            return self.missing()
        with self.locked(create):
            if self.cancelled():
                operation, create = 'status', False
            record = self.record()
            if record and not self.owns(record):
                self.forget()
                record = None
            if operation == 'stop':
                if record:
                    self.stop_owned(record)
                    self.forget()
                return self.missing()
            created = record is None and create
            if record is None:
                if not create:
                    return self.missing()
                record, reply = self.launch()
            else:
                try:
                    reply = self.ipc(record, 'status')
                    self.validate(record, reply)
                except (ControlError, OSError):
                    if operation != 'close':
                        raise
                    # Close must release the input grab even if the UI event loop
                    # cannot answer or the reply is incompatible after an upgrade.
                    # OS ownership is checked again by stop_owned.
                    self.stop_owned(record)
                    self.forget()
                    return self.missing()
            try:
                if self.cancelled() and operation in ('start', 'open', 'toggle'):
                    return self.validate(record, self.ipc(record, 'close', min(self.timeout, 0.5)))
                if operation in ('open', 'close', 'toggle'):
                    reply = self.ipc(record, operation)
                    self.validate(record, reply)
                if operation in ('open', 'toggle'):
                    deadline = self.deadline
                    while reply['pending']:
                        if self.cancelled():
                            return self.validate(record, self.ipc(record, 'close', min(self.timeout, 0.5)))
                        if time.monotonic() >= deadline:
                            # Withdraw the pending request so a late unlock cannot open it.
                            self.ipc(record, 'close', min(self.timeout, 0.5))
                            raise ControlError('Overview lock verification timed out; retry when unlocked.')
                        time.sleep(0.03)
                        reply = self.ipc(record, 'status', max(0.001, deadline - time.monotonic()))
                        self.validate(record, reply)
                if self.cancelled() and operation in ('open', 'toggle'):
                    reply = self.ipc(record, 'close', min(self.timeout, 0.5))
                return self.validate(record, reply)
            except BaseException as error:
                if created or operation == 'close':
                    self.stop_owned(record)
                    self.forget()
                    if operation == 'close' and isinstance(error, (ControlError, OSError)):
                        return self.missing()
                elif operation in ('open', 'toggle'):
                    # A lost reply must not leave a pending request that opens later.
                    try:
                        self.ipc(record, 'close', min(self.timeout, 0.5))
                    except ControlError:
                        self.stop_owned(record)
                        self.forget()
                raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=OPERATIONS)
    args = parser.parse_args()
    try:
        response = Controller().execute(args.operation)
    except (ControlError, OSError) as exc:
        # OSError strings can contain paths and third-party output; use fixed text.
        message = str(exc) if isinstance(exc, ControlError) else 'Overview could not be controlled; check the installation and runtime permissions.'
        print(json.dumps({'ok': False, 'error': message}))
        return 1
    print(json.dumps(response))
    return 0


if __name__ == '__main__':
    sys.exit(main())
