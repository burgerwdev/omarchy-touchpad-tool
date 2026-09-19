#!/usr/bin/env python3
"""Real Quickshell IPC with an isolated offscreen shell and fake lock observer.

No compositor connection, window capture, gesture, or desktop mutation occurs.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('overview_control', REPO / 'overview-control.py')
control = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(control)


class RealIpcTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='overview ipc ')
        self.root = Path(self.temp.name)
        (self.root / 'overview').mkdir()
        shutil.copy2(REPO / 'overview/Session.qml', self.root / 'overview/Session.qml')
        (self.root / 'overview/shell.qml').write_text('import Quickshell\nShellRoot { Session {} }\n')
        # Fake observer serves controlled states only; no real Wayland connection.
        (self.root / 'overview/lock-watch.py').write_text('''import os, select, sys, time
from pathlib import Path
assert sys.argv[1:] == ['--format', 'plain', '--exit-on-consumer-close'], sys.argv
poll = select.poll()
poll.register(sys.stdout.fileno(), select.POLLERR | select.POLLHUP)
path = Path(os.environ['TEST_LOCK_STATE'])
previous = None
print('unknown', flush=True)
while True:
    if poll.poll(0): break
    value = path.read_text().strip()
    if value == 'exit': break
    if value != previous:
        print(value, flush=True); previous = value
    time.sleep(0.02)
''')
        shutil.copy2(REPO / 'manifest.json', self.root / 'manifest.json')
        self.runtime = self.root / 'runtime'; self.runtime.mkdir(mode=0o700)
        self.lock_state = self.root / 'lock'; self.lock_state.write_text('unlocked')
        self.env = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QPA_PLATFORMTHEME='basic',
                        QT_QUICK_CONTROLS_STYLE='Basic', XDG_RUNTIME_DIR=str(self.runtime),
                        WAYLAND_DISPLAY='nonexistent-test-compositor',
                        HYPRLAND_INSTANCE_SIGNATURE='isolated-overview-test',
                        TEST_LOCK_STATE=str(self.lock_state))
        self.c = control.Controller(self.root, self.runtime, 'isolated-test', env=self.env)

    def tearDown(self):
        try: self.c.execute('stop')
        finally:
            if self.c.last_spawn is not None:
                if self.c.last_spawn.poll() is None: self.c.last_spawn.kill()
                self.c.last_spawn.wait()
            self.temp.cleanup()

    def wait_state(self, **expected):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            reply = self.c.execute('status')
            if all(reply.get(key) == value for key, value in expected.items()): return reply
            time.sleep(0.03)
        self.fail('Lifecycle state did not settle: ' + repr(expected))

    def test_authenticated_lifecycle_and_fail_closed_lock(self):
        reply = self.c.execute('start')
        self.assertFalse(reply['opened']); self.assertFalse(reply['rendered'])
        self.wait_state(lockState='unlocked')
        record = json.loads(self.c.record_path.read_text())
        # Typed mutations reject tokens even when addressed directly by PID.
        wrong = dict(record, token='0'*64)
        self.assertEqual(self.c.ipc(wrong, 'open'), {'error': 'unauthorized'})
        self.assertFalse(self.c.execute('status')['opened'])
        self.c.execute('open'); self.wait_state(opened=True)
        self.lock_state.write_text('locked'); self.wait_state(lockState='locked', opened=False, rendered=False)
        self.lock_state.write_text('unlocked'); self.wait_state(lockState='unlocked', opened=False)
        self.c.execute('open'); self.wait_state(opened=True)
        self.lock_state.write_text('unknown'); self.wait_state(lockState='unknown', opened=False)
        self.lock_state.write_text('unlocked'); self.wait_state(lockState='unlocked', opened=False)
        self.c.execute('open'); self.wait_state(opened=True)
        self.lock_state.write_text('exit'); self.wait_state(lockState='unknown', opened=False, pending=False)
        self.lock_state.write_text('unlocked')
        time.sleep(0.1)
        self.assertEqual('unknown', self.c.execute('status')['lockState'])
        self.c.execute('open'); self.wait_state(lockState='unlocked', opened=True)
        self.c.execute('close'); self.wait_state(opened=False)
        self.assertFalse(self.c.execute('stop')['reachable'])

    def test_toggle_lifecycle_and_unknown_lock_cancellation(self):
        self.c.execute('start')
        self.wait_state(lockState='unlocked', opened=False)
        self.assertTrue(self.c.execute('toggle')['opened'])
        self.assertFalse(self.c.execute('toggle')['opened'])
        self.lock_state.write_text('locked')
        self.wait_state(lockState='locked')
        self.assertFalse(self.c.execute('toggle')['opened'])
        self.lock_state.write_text('unknown')
        self.wait_state(lockState='unknown')
        self.c.timeout = .3
        with self.assertRaises(control.ControlError):
            self.c.execute('toggle')
        self.wait_state(opened=False, pending=False)
        self.lock_state.write_text('unlocked')
        self.wait_state(lockState='unlocked', opened=False, pending=False)


if __name__ == '__main__': unittest.main()
