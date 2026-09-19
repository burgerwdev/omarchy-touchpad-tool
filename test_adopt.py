"""Conflict handling: detect other tools, back up first, import, and disable only.

The real CLI runs in a copied plugin directory against a fake compositor and a
fake `omarchy` command, so backups and the two user-visible actions are checked
as files and command calls.
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
OTHER = 'davefano.trackpad-plus'
FAKE_HYPRCTL = '''
import json, os, sys
root = os.environ['ADOPT_TEST_ROOT']
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
if args[:1] == ['reload']:
    print('ok'); raise SystemExit(0)
if args[:1] == ['configerrors']:
    print(''); raise SystemExit(0)
print('')
'''
FAKE_OMARCHY = '''
import json, os, sys
root = os.environ['ADOPT_TEST_ROOT']
args = sys.argv[1:]
with open(os.path.join(root, 'omarchy.log'), 'a') as log:
    log.write(' '.join(args) + '\\n')
if args[:2] == ['plugin', 'list']:
    print(json.dumps([
        {'id': 'local.touchpad-tool', 'name': 'Touchpad Tool', 'enabled': True},
        {'id': 'davefano.trackpad-plus', 'name': 'Trackpad Plus', 'enabled': True},
        {'id': 'omarchy.audio', 'name': 'Audio', 'enabled': True},
    ]))
elif args[:2] == ['plugin', 'disable']:
    print('Disabled ' + args[2])
else:
    print('')
'''
LEGACY_INPUT = '''-- user input
-- BEGIN io.github.artmoreno.trackpoint device (managed by the TrackPoint bar widget)
hl.device({
  name = "tpps/2-elan-trackpoint",
  sensitivity = 0.35,
})
-- END io.github.artmoreno.trackpoint device
-- Trackpad Plus original gesture location
-- BEGIN Trackpad Plus gestures
hl.gesture({ fingers = 3, direction = "horizontal", action = "workspace" })
-- END Trackpad Plus gestures
'''
LEGACY_BINDS = '''-- user binds
-- BEGIN io.github.artmoreno.trackpoint middle button (managed by the TrackPoint bar widget)
o.bind("mouse:274", "TrackPoint middle button press", "python3 middle_button.py press")
-- END io.github.artmoreno.trackpoint middle button
'''


class AdoptTests(unittest.TestCase):
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
        self.input = self.config / 'input.lua'
        self.bindings = self.config / 'bindings.lua'
        self.input.write_text(LEGACY_INPUT)
        self.bindings.write_text(LEGACY_BINDS)
        self.state = self.root / 'state'
        self.devices = self.root / 'devices.json'
        self.devices.write_text(json.dumps({'mice': [{'name': TOUCHPAD}, {'name': TRACKPOINT}]}))
        for name, body in (('hyprctl', FAKE_HYPRCTL), ('omarchy', FAKE_OMARCHY)):
            fake = self.root / name
            fake.write_text('#!' + sys.executable + body)
            fake.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.root), ADOPT_TEST_ROOT=str(self.root),
                        XDG_STATE_HOME=str(self.state), XDG_CONFIG_HOME=str(self.root / '.config'),
                        PATH=str(self.root) + os.pathsep + os.environ['PATH'])
        self.backups = self.state / 'omarchy/touchpad-tool/backups'

    def adopt(self, *args, expect_success=True):
        result = subprocess.run([sys.executable, str(self.plugin / 'adopt.py'), *args],
                                env=self.env, capture_output=True, text=True, timeout=30)
        if expect_success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout), result.returncode

    def omarchy_calls(self):
        log = self.root / 'omarchy.log'
        return log.read_text().splitlines() if log.exists() else []

    def rules(self):
        return (self.state / 'omarchy/toggles/hypr/zz-local-touchpads.lua').read_text()

    def test_status_reports_the_other_plugin_and_legacy_blocks(self):
        payload, _ = self.adopt('status')
        self.assertEqual([p['id'] for p in payload['others']], [OTHER])
        self.assertEqual(payload['enabled_others'], [OTHER])
        self.assertTrue(payload['needs_attention'])
        markers = [block['marker'] for block in payload['legacy']]
        self.assertTrue(any('artmoreno.trackpoint device' in marker for marker in markers))
        self.assertTrue(any('artmoreno.trackpoint middle button' in marker for marker in markers))
        self.assertTrue(any('Trackpad Plus gestures' in marker for marker in markers))
        self.assertEqual(payload['remove_hint'], [f'omarchy plugin remove {OTHER}'])

    def test_status_alone_changes_nothing(self):
        before = (self.input.read_bytes(), self.bindings.read_bytes())
        self.adopt('status')
        self.assertEqual((self.input.read_bytes(), self.bindings.read_bytes()), before)
        self.assertFalse(self.backups.exists(), 'status must not create a backup')
        self.assertFalse((self.state / 'omarchy/local-touchpads/settings.json').exists())

    def test_backup_copies_every_file_it_owns_and_is_private(self):
        payload, _ = self.adopt('backup')
        folder = Path(payload['folder'])
        self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
        names = sorted(f['name'] for f in payload['files'])
        self.assertEqual(names, ['bindings.lua', 'input.lua'])
        for item in payload['files']:
            info = (folder / item['name']).stat()
            self.assertEqual(info.st_mode & 0o777, 0o600)
        manifest = json.loads((folder / 'manifest.json').read_text())
        self.assertEqual(manifest['plugin'], 'local.touchpad-tool')
        self.assertTrue(all('source' in entry for entry in manifest['files']))

    def test_import_migrates_blocks_and_the_pinned_sensitivity(self):
        payload, _ = self.adopt('import')
        self.assertTrue(self.backups.exists(), 'import must back up first')
        folder = next(p for p in self.backups.iterdir() if p.is_dir())
        self.assertEqual((folder / 'input.lua').read_text(), LEGACY_INPUT, 'backup holds the pre-change file')
        input_text = self.input.read_text()
        self.assertNotIn('artmoreno.trackpoint device', input_text)
        self.assertIn('-- BEGIN local.touchpad-tool gestures', input_text)
        self.assertNotIn('Trackpad Plus gestures', input_text)
        self.assertIn('-- local.touchpad-tool original gesture location', input_text)
        binds = self.bindings.read_text()
        self.assertIn('-- BEGIN local.touchpad-tool middle button', binds)
        self.assertNotIn('artmoreno', binds)
        # The pinned sensitivity is now owned by the generated rules.
        self.assertIn('sensitivity = 0.35', self.rules())
        state = json.loads((self.state / 'omarchy/local-touchpads/settings.json').read_text())
        self.assertEqual(state['devices'][TRACKPOINT]['settings']['sensitivity'], 0.35)
        self.assertTrue(any('sensitivity' in action for action in payload['actions']))

    def test_import_keeps_other_options_the_block_held(self):
        self.input.write_text(LEGACY_INPUT.replace(
            '  sensitivity = 0.35,\n', '  sensitivity = 0.35,\n  scroll_factor = 0.5,\n'))
        self.adopt('import')
        input_text = self.input.read_text()
        self.assertIn('scroll_factor = 0.5', input_text, 'unrelated options stay where the user wrote them')
        self.assertNotIn('sensitivity', input_text)
        self.assertIn('sensitivity = 0.35', self.rules())

    def test_disable_backs_up_first_and_never_removes(self):
        payload, _ = self.adopt('disable', OTHER)
        self.assertEqual(payload['disabled'], OTHER)
        self.assertTrue(self.backups.exists())
        calls = self.omarchy_calls()
        self.assertIn(f'plugin disable {OTHER}', calls)
        self.assertFalse(any('remove' in call for call in calls), 'removal is never executed')
        self.assertIn(f'omarchy plugin remove {OTHER}', payload['uninstall_hint'])

    def test_refuses_to_disable_itself(self):
        payload, code = self.adopt('disable', 'local.touchpad-tool', expect_success=False)
        self.assertEqual(code, 1)
        self.assertIn('Refusing', payload['error'])
        self.assertFalse(any('disable' in call for call in self.omarchy_calls()))

    def test_removal_is_only_ever_instructed(self):
        source = Path('adopt.py').read_text()
        # Removal appears only as the hint text this plugin shows the user.
        self.assertIn("REMOVE_HINT = 'omarchy plugin remove'", source)
        self.assertNotIn("'remove'", source)
        self.assertNotIn('"remove"', source)
        panel = Path('Panel.qml').read_text()
        self.assertNotIn('plugin", "remove', panel)
        # And there is no command that would attempt it.
        payload, code = self.adopt('remove', OTHER, expect_success=False)
        self.assertEqual(code, 1)
        self.assertIn('Usage', payload['error'])
        self.assertFalse(any('remove' in call for call in self.omarchy_calls()))


if __name__ == '__main__':
    unittest.main()
