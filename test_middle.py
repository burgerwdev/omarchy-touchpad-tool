"""Middle button: bind block, scroll handoff through the shared writer, private state.

Runs the real CLI in a copied plugin directory against a fake compositor, so the
generated binds and the device settings it hands off are checked as files.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

TOUCHPAD = 'synaptics-tm3381-002'
TRACKPOINT = 'tpps/2-elan-trackpoint'
FAKE_COMPOSITOR = '''
import json, os, sys
root = os.environ['MIDDLE_TEST_ROOT']
args = sys.argv[1:]
if args[:1] == ['devices']:
    print(open(os.path.join(root, 'devices.json')).read()); raise SystemExit(0)
if args[:1] == ['getoption']:
    option = args[1]
    print(json.dumps({'float': 0.2} if option.endswith(('sensitivity', 'scroll_factor')) else {'bool': True}))
    raise SystemExit(0)
if args[:1] == ['eval']:
    with open(os.path.join(root, 'eval.log'), 'a') as log:
        log.write(args[1] + '\\n')
    print('ok'); raise SystemExit(0)
if args[:1] == ['activewindow']:
    print(json.dumps({'class': 'Zen'})); raise SystemExit(0)
if args[:1] == ['reload']:
    print('ok'); raise SystemExit(0)
if args[:1] == ['configerrors']:
    print(''); raise SystemExit(0)
print('')
'''


class MiddleButtonTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.plugin = self.root / 'plugin'
        self.plugin.mkdir()
        repo = Path(__file__).resolve().parent
        tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=repo).decode().split('\0')
        for name in filter(None, tracked):
            source = repo / name
            if source.is_file():
                destination = self.plugin / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        self.config = self.root / '.config/hypr'
        self.config.mkdir(parents=True)
        self.bindings = self.config / 'bindings.lua'
        self.bindings.write_text('-- the user binds\n')
        self.original = self.bindings.read_bytes()
        self.state = self.root / 'state'
        self.devices = self.root / 'devices.json'
        self.write_devices([TOUCHPAD, TRACKPOINT])
        fake = self.root / 'hyprctl'
        fake.write_text('#!' + sys.executable + FAKE_COMPOSITOR)
        fake.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.root), MIDDLE_TEST_ROOT=str(self.root),
                        XDG_STATE_HOME=str(self.state), XDG_CONFIG_HOME=str(self.root / '.config'),
                        PATH=str(self.root) + os.pathsep + os.environ['PATH'])
        self.store = self.state / 'omarchy/trackpoint/middle.json'

    def write_devices(self, names):
        self.devices.write_text(json.dumps({'mice': [{'name': name} for name in names]}))

    def middle(self, *args, expect_success=True):
        result = subprocess.run([sys.executable, str(self.plugin / 'middle.py'), *args],
                                env=self.env, capture_output=True, text=True, timeout=30)
        if expect_success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout), result.returncode

    def rules(self):
        return (self.state / 'omarchy/toggles/hypr/zz-local-touchpads.lua').read_text()

    def settings(self):
        state = json.loads((self.state / 'omarchy/local-touchpads/settings.json').read_text())
        return state['devices'][TRACKPOINT]['settings']

    def test_binds_are_generated_and_scrolling_is_handed_off(self):
        self.middle('set', 'default', 'tap', 'omarchy-launch-terminal')
        self.middle('enable')
        written = self.bindings.read_text()
        self.assertIn('-- BEGIN local.touchpad-tool middle button', written)
        self.assertIn('-- END local.touchpad-tool middle button', written)
        self.assertIn('mouse:274', written)
        self.assertIn('middle_button.py press', written)
        # Hold-to-scroll is released through the one device writer.
        self.assertEqual(self.settings().get('scroll_method'), 'no_scroll')
        self.assertIn('scroll_method = "no_scroll"', self.rules())
        self.assertTrue(self.store.exists())
        self.assertIn('scroll_method', (self.root / 'eval.log').read_text())

    def test_disable_restores_scrolling_and_removes_the_block(self):
        self.middle('set', 'default', 'tap', 'omarchy-launch-terminal')
        self.middle('enable')
        self.middle('disable')
        self.assertEqual(self.bindings.read_bytes(), self.original)
        # Disabling hands scrolling back. The TrackPoint stays a managed device
        # (enabling configured it), so its sensitivity rule remains as before.
        self.assertNotIn('scroll_method', self.settings())
        self.assertNotIn('scroll_method', self.rules())
        self.assertIn(TRACKPOINT, self.rules())
        self.assertFalse(self.middle()[0]['enabled'])

    def test_modifier_and_flick_actions_get_their_own_binds(self):
        self.middle('set', 'default', 'super', 'omarchy-menu toggle root')
        self.middle('set', 'default', 'up', 'omarchy-launch-browser')
        self.middle('enable')
        written = self.bindings.read_text()
        self.assertIn('o.bind("SUPER + mouse:274", "TrackPoint middle button Super tap"', written)
        self.assertIn('o.bind("mouse:274", "TrackPoint middle button release"', written)

    def test_app_profiles_are_added_and_removed(self):
        self.middle('add-app', 'Zen')
        self.middle('set', 'Zen', 'tap', ':')
        profiles = self.middle()[0]['profiles']
        self.assertEqual(profiles['Zen']['tap'], ':')
        self.middle('remove-app', 'Zen')
        self.assertNotIn('Zen', self.middle()[0]['profiles'])

    def test_state_file_is_private(self):
        self.middle('set', 'default', 'tap', 'true')
        info = self.store.stat()
        self.assertEqual(info.st_mode & 0o777, 0o600)
        self.assertEqual(info.st_nlink, 1)

    def test_unknown_slot_is_refused_without_touching_the_config(self):
        payload, code = self.middle('set', 'default', 'nonsense', 'x', expect_success=False)
        self.assertEqual(code, 1)
        self.assertIn('Unknown action', payload['error'])
        self.assertEqual(self.bindings.read_bytes(), self.original)

    def test_enable_without_a_trackpoint_reports_an_error(self):
        self.write_devices([TOUCHPAD])
        payload, code = self.middle('enable', expect_success=False)
        self.assertEqual(code, 1)
        self.assertIn('No TrackPoint found', payload['error'])
        self.assertEqual(self.bindings.read_bytes(), self.original)


if __name__ == '__main__':
    unittest.main()
