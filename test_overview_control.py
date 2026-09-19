#!/usr/bin/env python3
"""Lifecycle contract with owned fake Quickshell processes, no desktop access."""
import concurrent.futures
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('overview_control', Path(__file__).with_name('overview-control.py'))
control = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(control)

FAKE = '''#!/usr/bin/env python3
import json, os, socket, sys, time
from pathlib import Path
root = Path(os.environ['XDG_RUNTIME_DIR'])
if sys.argv[1] == 'ipc':
    pid = sys.argv[sys.argv.index('--pid')+1]
    with socket.socket(socket.AF_UNIX) as s:
        s.connect(str(root / ('fake-' + pid)))
        s.sendall(json.dumps(sys.argv[sys.argv.index('call')+2:]).encode())
        print(s.recv(65536).decode())
    sys.exit()
mode = os.environ.get('FAKE_MODE', '')
if mode == 'hang': time.sleep(30)
path = root / ('fake-' + str(os.getpid()))
s = socket.socket(socket.AF_UNIX); s.bind(str(path)); s.listen()
opened = False
while True:
    conn, _ = s.accept()
    with conn:
        args = json.loads(conn.recv(65536)); op = args[0]
        if mode == 'timeout' or (root / 'hang-now').exists() or (op == 'close' and (root / 'hang-close').exists()): time.sleep(30)
        if mode == 'slow': time.sleep(.18)
        if mode == 'oversized': conn.sendall(b'x'*20000); continue
        if mode == 'malformed': conn.sendall(b'not-json'); continue
        if op != 'status' and args[1] != os.environ['TRACKPAD_OVERVIEW_TOKEN']:
            conn.sendall(b'{"error":"unauthorized"}'); continue
        if op == 'open': opened = True
        if op == 'toggle': opened = not opened
        if op == 'close': opened = False
        data = dict(protocol=1, version=os.environ['TRACKPAD_OVERVIEW_VERSION'], session=os.environ['TRACKPAD_OVERVIEW_SESSION'], pid=os.getpid(), instance='fake-instance', config=sys.argv[sys.argv.index('-p')+1], opened=opened, pending=False, lockState='unlocked', rendered=False, result='opened' if opened else 'hidden')
        if mode == 'wrong-version': data['version'] = 'wrong'
        if mode == 'wrong-session': data['session'] = 'wrong'
        conn.sendall(json.dumps(data).encode())
        if op == 'stop': sys.exit()
'''


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='overview tests ')
        self.root = Path(self.temp.name)
        self.runtime = self.root / 'runtime'; self.runtime.mkdir(mode=0o700)
        self.base = self.root / 'install with spaces'; (self.base / 'overview').mkdir(parents=True)
        (self.base / 'overview/shell.qml').write_text('// fixture')
        (self.base / 'manifest.json').write_text('{"version":"2026.09.14.1"}')
        self.qs = self.root / 'fake qs'; self.qs.write_text(FAKE); self.qs.chmod(0o700)
        self.env = dict(os.environ, XDG_RUNTIME_DIR=str(self.runtime))
        self.controllers = []
        self.c = self.make()

    def make(self, **env):
        obj = control.Controller(self.base, self.runtime, 'compositor-session', str(self.qs), dict(self.env, **env), timeout=0.7)
        self.controllers.append(obj)
        return obj

    def tearDown(self):
        for c in self.controllers:
            try: c.execute('stop')
            except (control.ControlError, OSError): pass
            if c.last_spawn is not None:
                if c.last_spawn.poll() is None: c.last_spawn.kill()
                c.last_spawn.wait()
        self.temp.cleanup()

    def test_missing_inspection_and_close_never_launch(self):
        for op in ('status', 'close', 'stop'):
            self.assertFalse(self.c.execute(op)['reachable'])
        self.assertFalse(self.c.directory.exists())

    def test_start_is_capture_free_and_space_paths_work(self):
        first = self.c.execute('start')
        self.assertTrue(first['reachable'])
        self.assertFalse(first['opened'])
        self.assertFalse(first['rendered'])
        self.assertEqual(first['pid'], self.c.execute('start')['pid'])
        self.assertTrue(self.c.execute('open')['opened'])
        self.assertFalse(self.c.execute('close')['opened'])
        self.assertFalse(self.c.execute('stop')['reachable'])

    def test_toggle_opens_and_closes_same_instance(self):
        first = self.c.execute('toggle')
        self.assertTrue(first['opened'])
        second = self.c.execute('toggle')
        self.assertEqual(first['pid'], second['pid'])
        self.assertFalse(second['opened'])

    def test_close_stops_an_owned_unresponsive_overview(self):
        reply = self.c.execute('open')
        (self.runtime / 'hang-now').touch()
        with self.assertRaises(control.ControlError):
            self.c.execute('status')
        os.kill(reply['pid'], 0)  # Status inspection never terminates it.
        began = time.monotonic()
        self.assertFalse(self.c.execute('close')['reachable'])
        self.assertLess(time.monotonic() - began, 2)
        self.c.last_spawn.wait(timeout=2)
        self.assertFalse(self.c.record_path.exists())

    def test_concurrent_open_has_one_instance(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(lambda _: self.make().execute('open'), range(2)))
        self.assertEqual(replies[0]['pid'], replies[1]['pid'])
        self.assertTrue(all(r['opened'] for r in replies))

    def test_later_close_cancels_older_open_waiting_for_lock(self):
        self.c.execute('start')
        queued = threading.Event()
        release = threading.Event()
        opener = self.make()
        flock = control.fcntl.flock

        def observe(fd, operation):
            try:
                return flock(fd, operation)
            except BlockingIOError:
                if threading.current_thread().name == 'earlier-open':
                    queued.set()
                    release.wait(2)
                raise

        result = {}
        with patch.object(control.fcntl, 'flock', side_effect=observe):
            with self.c.locked(False):
                worker = threading.Thread(name='earlier-open',
                    target=lambda: result.update(opener.execute('open')))
                worker.start()
                self.assertTrue(queued.wait(2))
            try:
                self.assertFalse(self.make().execute('close')['opened'])
            finally:
                release.set()
                worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertFalse(result['opened'])
        self.assertFalse(self.c.execute('status')['opened'])
        # A fresh upward gesture after the close must still work.
        self.assertTrue(self.make().execute('open')['opened'])

    def test_close_during_startup_cancels_open(self):
        started = threading.Event()
        proceed = threading.Event()
        opener = self.make()
        launch = opener.launch
        result = {}
        def slow_launch():
            started.set()
            self.assertTrue(proceed.wait(2))
            return launch()
        with patch.object(opener, 'launch', side_effect=slow_launch):
            worker = threading.Thread(target=lambda: result.update(opener.execute('open')))
            worker.start()
            self.assertTrue(started.wait(2))
            closer = self.make()
            close_result = {}
            close_worker = threading.Thread(target=lambda: close_result.update(closer.execute('close')))
            close_worker.start()
            # Wait until the close has registered its intent, without depending
            # on which contender the OS wakes first after startup.
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline and not opener.cancelled():
                time.sleep(.005)
            proceed.set()
            worker.join(3)
            close_worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertFalse(close_worker.is_alive())
        self.assertFalse(result['opened'])
        self.assertFalse(close_result['opened'])
        self.assertFalse(self.c.execute('status')['opened'])

    def test_startup_and_open_share_one_deadline(self):
        controller = self.make(FAKE_MODE='slow')
        controller.timeout = .3
        began = time.monotonic()
        with self.assertRaises(control.ControlError):
            controller.execute('open')
        self.assertLess(time.monotonic() - began, .9)
        controller.last_spawn.wait(timeout=1)
        self.assertFalse(controller.record_path.exists())

    def test_close_ipc_timeout_stops_owned_process(self):
        self.c.execute('open')
        (self.runtime / 'hang-close').touch()
        self.assertFalse(self.c.execute('close')['reachable'])
        self.c.last_spawn.wait(timeout=2)
        self.assertFalse(self.c.record_path.exists())

    def test_close_after_in_place_upgrade_stops_owned_old_version(self):
        first = self.c.execute('open')
        (self.base / 'manifest.json').write_text('{"version":"2026.09.15.0"}')
        upgraded = self.make()
        for operation in ('status', 'start', 'open', 'toggle'):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(control.ControlError, 'handshake failed'):
                    upgraded.execute(operation)
                os.kill(first['pid'], 0)
        self.assertFalse(upgraded.execute('close')['reachable'])
        self.c.last_spawn.wait(timeout=2)
        self.assertFalse(upgraded.record_path.exists())

    def test_close_invalid_status_stops_only_verified_owned_process(self):
        self.c.execute('open')
        original_ipc = self.c.ipc

        def invalid_status(record, operation, timeout=None):
            reply = original_ipc(record, operation, timeout)
            if operation == 'status':
                reply['protocol'] = 999
            return reply

        with patch.object(self.c, 'ipc', side_effect=invalid_status):
            self.assertFalse(self.c.execute('close')['reachable'])
        self.c.last_spawn.wait(timeout=2)
        self.assertFalse(self.c.record_path.exists())

    def test_failed_close_termination_retains_record(self):
        self.c.execute('open')
        original = self.c.record_path.read_bytes()
        (self.runtime / 'hang-now').touch()
        with patch.object(self.c, 'stop_owned', side_effect=control.ControlError('still running')):
            with self.assertRaisesRegex(control.ControlError, 'still running'):
                self.c.execute('close')
        self.assertEqual(self.c.record_path.read_bytes(), original)

    def test_unconfirmed_termination_retains_record(self):
        reply = self.c.execute('start')
        original = self.c.record_path.read_bytes()
        with patch.object(control.signal, 'pidfd_send_signal') as send_signal, \
                patch.object(control.select, 'select', return_value=([], [], [])):
            with self.assertRaisesRegex(control.ControlError, 'did not stop'):
                self.c.execute('stop')
            self.assertEqual([call.args[1] for call in send_signal.call_args_list],
                             [control.signal.SIGTERM, control.signal.SIGKILL])
        self.assertEqual(self.c.record_path.read_bytes(), original)
        os.kill(reply['pid'], 0)

    def test_wrong_token_cannot_mutate_or_stop_owned_process(self):
        reply = self.c.execute('start')
        record = json.loads(self.c.record_path.read_text()); record['token'] = '0'*64
        self.c.record_path.write_text(json.dumps(record))
        for op in ('close', 'stop', 'open'):
            with self.assertRaises(control.ControlError): self.c.execute(op)
        os.kill(reply['pid'], 0)
        # Restore the original record only for this test's owned cleanup.
        record['token'] = self.c.last_spawn_token
        self.c.record_path.write_text(json.dumps(record))

    def test_unrelated_pid_is_not_signaled(self):
        unrelated = subprocess.Popen(['sleep', '30'])
        try:
            self.c.execute('start')
            record = self.c.record_path.read_text()
            altered = json.loads(record); altered['pid'] = unrelated.pid
            altered['start'] = control.process_info(unrelated.pid)['start']
            self.c.record_path.write_text(json.dumps(altered))
            with self.assertRaises(control.ControlError): self.c.execute('stop')
            self.assertIsNone(unrelated.poll())
            self.c.record_path.write_text(record)
        finally:
            unrelated.terminate(); unrelated.wait()

    def test_stale_pid_record_recovers_only_explicit_start(self):
        self.c.execute('start')
        record = json.loads(self.c.record_path.read_text())
        self.c.execute('stop')
        record['pid'] = 2147483647
        self.c.record_path.write_text(json.dumps(record))
        self.assertFalse(self.c.execute('status')['reachable'])
        self.assertTrue(self.c.execute('start')['reachable'])

    def test_reused_live_pid_recovers_without_signaling_it(self):
        self.c.execute('start')
        record = json.loads(self.c.record_path.read_text())
        self.c.execute('stop')
        unrelated = subprocess.Popen(['sleep', '30'])
        try:
            record['pid'] = unrelated.pid
            record['start'] = str(int(control.process_info(unrelated.pid)['start']) - 1)
            for op in ('status', 'close', 'stop', 'start', 'open', 'toggle'):
                with self.subTest(operation=op):
                    self.c.record_path.write_text(json.dumps(record))
                    with patch.object(control.signal, 'pidfd_send_signal') as send_signal:
                        reply = self.c.execute(op)
                        send_signal.assert_not_called()
                    self.assertIsNone(unrelated.poll())
                    self.assertEqual(reply['reachable'], op in ('start', 'open', 'toggle'))
                    if reply['reachable']:
                        self.assertNotEqual(reply['pid'], unrelated.pid)
                        self.c.execute('stop')
                    else:
                        self.assertFalse(self.c.record_path.exists())
        finally:
            unrelated.terminate(); unrelated.wait()

    def test_malformed_identity_and_same_process_mismatch_fail_closed(self):
        self.c.execute('start')
        original = json.loads(self.c.record_path.read_text())
        for key, value in (('start', None), ('start', 'invalid'), ('start', 42),
                           ('token', ''), ('argv', None), ('config', '/other/shell.qml'),
                           ('session', 'other-session')):
            with self.subTest(key=key, value=value):
                altered = dict(original, **{key: value})
                self.c.record_path.write_text(json.dumps(altered))
                with patch.object(control.signal, 'pidfd_send_signal') as send_signal:
                    for op in ('status', 'close', 'stop', 'start', 'open', 'toggle'):
                        with self.assertRaises(control.ControlError):
                            self.c.execute(op)
                    send_signal.assert_not_called()
                self.assertEqual(json.loads(self.c.record_path.read_text()), altered)
        self.c.record_path.write_text(json.dumps(original))

    def test_failed_launches_are_bounded_and_reaped(self):
        for mode in ('hang', 'timeout', 'malformed', 'oversized', 'wrong-version', 'wrong-session'):
            with self.subTest(mode=mode):
                c = self.make(FAKE_MODE=mode)
                began = time.monotonic()
                with self.assertRaises(control.ControlError): c.execute('start')
                self.assertLess(time.monotonic() - began, 2.5)
                self.assertIsNotNone(c.last_spawn.poll())
                self.assertFalse(c.record_path.exists())

    def test_existing_handshake_mismatch_is_not_replaced(self):
        reply = self.c.execute('start')
        self.c.version = 'new-version'
        for op in ('status', 'start', 'open', 'toggle'):
            with self.assertRaises(control.ControlError): self.c.execute(op)
        os.kill(reply['pid'], 0)
        # Stop may remove an old version only after OS-level ownership validation.
        self.assertFalse(self.c.execute('stop')['reachable'])

    def test_lock_timeout_is_bounded(self):
        import fcntl
        self.c.execute('start')
        with self.c.lock_path.open('r+') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            with self.assertRaises(control.ControlError): self.c.execute('status')

    def test_symlink_record_is_rejected(self):
        self.c.directory.mkdir(mode=0o700, parents=True)
        target = self.root / 'other'; target.write_text('{}')
        self.c.record_path.symlink_to(target)
        with self.assertRaises(control.ControlError): self.c.execute('start')
        self.assertEqual('{}', target.read_text())

    def test_operation_is_allowlisted(self):
        with self.assertRaises(control.ControlError): self.c.execute('anything; bad')


if __name__ == '__main__':
    unittest.main()
