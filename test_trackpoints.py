"""The TrackPoint writes through the same writer as the touchpad.

Two regressions found by running the writer against the real compositor are
covered here: a rediscovered TrackPoint must keep its kind (it was initialized
with touchpad settings), and the legacy touchpad migration must not touch a
TrackPoint group (it crashed on the missing scroll_factor).
"""
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import trackpads as m

TOUCHPAD = 'synaptics-tm3381-002'
TRACKPOINT = 'tpps/2-elan-trackpoint'
MICE = [{'name': TOUCHPAD}, {'name': TRACKPOINT}, {'name': 'usb-mouse'}]


def compositor(*command):
    """A fake compositor: devices plus the options defaults() reads."""
    if command == ('devices', '-j'):
        return json.dumps({'mice': MICE})
    if command and command[0] == 'getoption':
        if command[1].endswith(('sensitivity', 'scroll_factor')):
            return json.dumps({'float': 0.2})
        return json.dumps({'bool': True})
    return 'ok'


class TrackPointWriterTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for name, value in [('DIRECTORY', root), ('STATE', root / 'settings.json'),
                            ('GENERATED', root / 'settings.lua')]:
            replacement = patch.object(m, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)

    def state(self):
        """The state one panel refresh would see, through the real session path."""
        with patch.object(m, 'hypr', side_effect=compositor):
            with m.session() as (state, live, previous):
                return copy.deepcopy(state), live

    def run_main(self, *args):
        with patch.object(m, 'hypr', side_effect=compositor) as run, \
                patch.object(m.sys, 'argv', ['trackpads.py', *args]), \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            m.main()
        return json.loads(output.getvalue()), run

    def test_group_all_tags_both_device_kinds(self):
        live = m.group_all(MICE)
        self.assertEqual(live[TOUCHPAD]['kind'], 'trackpad')
        self.assertEqual(live[TRACKPOINT]['kind'], 'trackpoint')
        self.assertEqual(live[TRACKPOINT]['names'], [TRACKPOINT])
        self.assertNotIn('usb-mouse', live)

    def test_initialize_gives_a_trackpoint_only_its_own_settings(self):
        with patch.object(m, 'defaults', return_value={'enabled': True, 'sensitivity': 0.25,
                                                       'scroll_factor': 0.2, 'natural_scroll': False,
                                                       'tap_to_click': True, 'clickfinger_behavior': True,
                                                       'disable_while_typing': True, 'accel_profile': 'adaptive'}):
            devices = m.initialize(m.group_all(MICE))['devices']
        self.assertEqual(devices[TRACKPOINT]['settings'], {'sensitivity': 0.25})
        self.assertEqual(devices[TRACKPOINT]['kind'], 'trackpoint')
        self.assertEqual(devices[TRACKPOINT]['label'], 'TrackPoint')
        self.assertTrue(set(m.BOOLS) <= set(devices[TOUCHPAD]['settings']))

    def test_discovered_trackpoint_keeps_its_kind(self):
        # Regression: routing known interfaces dropped the kind, so a fresh
        # TrackPoint was initialized with touchpad settings.
        state = {'version': 4, 'devices': {TOUCHPAD: {'id': TOUCHPAD, 'label': TOUCHPAD,
                                                      'names': [TOUCHPAD], 'configured': True,
                                                      'settings': {'enabled': True, 'sensitivity': 0.1,
                                                                   'scroll_factor': 0.2, 'natural_scroll': False,
                                                                   'tap_to_click': True,
                                                                   'clickfinger_behavior': True,
                                                                   'disable_while_typing': True}}}}
        routed = m.saved_device_owners(m.group_all(MICE), state)
        self.assertEqual(routed[TRACKPOINT]['kind'], 'trackpoint')
        initialized = m.initialize({TRACKPOINT: routed[TRACKPOINT]})['devices'][TRACKPOINT]
        self.assertEqual(initialized['kind'], 'trackpoint')
        self.assertEqual(set(initialized['settings']), {'sensitivity'})

    def test_legacy_migration_leaves_a_trackpoint_group_alone(self):
        # Regression: migration read settings['scroll_factor'] from every group
        # and crashed on a TrackPoint.
        state = {'version': 4, 'devices': {TRACKPOINT: {'id': TRACKPOINT, 'label': 'TrackPoint',
                                                        'names': [TRACKPOINT], 'kind': 'trackpoint',
                                                        'configured': True,
                                                        'settings': {'sensitivity': 0.4}}}}
        before = copy.deepcopy(state)
        self.assertEqual(m.migrate(state), before)
        self.assertEqual(state, before)

    def test_trackpoint_settings_are_validated_per_kind(self):
        base = {'id': TRACKPOINT, 'label': 'TrackPoint', 'names': [TRACKPOINT], 'kind': 'trackpoint',
                'configured': True, 'settings': {'sensitivity': 0.4}}
        m.validate_state({'version': 4, 'devices': {TRACKPOINT: base}})
        m.validate_state({'version': 4, 'devices': {TRACKPOINT: dict(
            base, settings={'sensitivity': 0.4, 'scroll_method': 'no_scroll'})}})
        for bad, message in [
            (dict(base, settings={'sensitivity': 0.4, 'tap_to_click': True}), 'Unknown setting'),
            (dict(base, settings={}), 'Missing device settings'),
            (dict(base, kind='joystick'), 'Unsupported device kind'),
            (dict(base, settings={'sensitivity': 0.4, 'scroll_method': 'middle'}), 'Unknown scroll method'),
        ]:
            with self.assertRaisesRegex(ValueError, message):
                m.validate_state({'version': 4, 'devices': {TRACKPOINT: bad}})

    def test_change_sets_and_clears_the_scroll_method(self):
        state, _ = self.state()
        with patch.object(m, 'hypr', side_effect=compositor):
            state = m.change(state, TRACKPOINT, 'scroll_method', 'no_scroll')
            self.assertEqual(state['devices'][TRACKPOINT]['settings']['scroll_method'], 'no_scroll')
            state = m.change(state, TRACKPOINT, 'scroll_method', None)
            self.assertNotIn('scroll_method', state['devices'][TRACKPOINT]['settings'])
            with self.assertRaisesRegex(ValueError, 'Only optional settings'):
                m.change(state, TRACKPOINT, 'sensitivity', None)
            with self.assertRaisesRegex(ValueError, 'Unknown setting'):
                m.change(state, TRACKPOINT, 'tap_to_click', True)

    def test_trackpoint_rules_go_to_the_generated_lua_only(self):
        state, _ = self.state()
        group = dict(state['devices'][TRACKPOINT], configured=True)
        lua = m.lua_for({TRACKPOINT: group})
        self.assertIn('local.touchpad-tool', lua)
        self.assertIn(f'name = "{TRACKPOINT}"', lua)
        self.assertIn('sensitivity = 0.2', lua)
        for touchpad_only in ('scroll_factor', 'tap_to_click', 'accel_profile', 'davefano'):
            self.assertNotIn(touchpad_only, lua)

    def test_unconfigured_trackpoint_emits_no_rules(self):
        state, _ = self.state()
        self.assertFalse(state['devices'][TRACKPOINT]['configured'])
        self.assertNotIn(TRACKPOINT, m.lua_for(state['devices']))

    def test_set_writes_state_and_rules_and_rejects_a_bad_value(self):
        _, state_run = self.run_main('state')
        # The first run saves the rules file; nothing is configured yet, so there
        # is no device rule to apply live.
        self.assertIn('local.touchpad-tool', m.GENERATED.read_text())
        del state_run
        _, set_run = self.run_main('set', TRACKPOINT, 'sensitivity', '0.3')
        saved = m.read_state_file(m.STATE)
        self.assertIn('"sensitivity": 0.3', saved)
        self.assertIn(f'name = "{TRACKPOINT}", sensitivity = 0.3', m.GENERATED.read_text())
        # An out-of-range value must not reach the compositor or either file.
        with self.assertRaisesRegex(ValueError, 'range'):
            self.run_main('set', TRACKPOINT, 'sensitivity', '5')
        self.assertEqual(m.read_state_file(m.STATE), saved)
        self.assertNotIn('sensitivity = 5', m.GENERATED.read_text())
        # Both runs applied the rules live, through the one apply path.
        self.assertTrue(any(call.args[0] == 'eval' for call in set_run.call_args_list))

    def test_no_entry_point_edits_the_users_hypr_config(self):
        with tempfile.TemporaryDirectory() as home:
            config = Path(home) / '.config/hypr'
            config.mkdir(parents=True)
            input_lua = config / 'input.lua'
            input_lua.write_text('-- the user config\n')
            before = input_lua.read_bytes()
            with patch.dict('os.environ', {'HOME': home}), patch.object(m, 'hypr', side_effect=compositor):
                self.run_main('state')
                self.run_main('set', TRACKPOINT, 'sensitivity', '0.3')
                self.run_main('set', TRACKPOINT, 'scroll_method', '"no_scroll"')
            self.assertEqual(input_lua.read_bytes(), before)
            self.assertEqual(sorted(p.name for p in config.iterdir()), ['input.lua'])
        for name in ('trackpads.py', 'control.py', 'trackpoint.py', 'devices.py'):
            self.assertNotIn('.config/hypr', Path(name).read_text(),
                             f'{name} must not write the user input config')

    def test_control_reads_and_writes_through_the_writer(self):
        spec = importlib.util.spec_from_file_location('control', Path(__file__).with_name('control.py'))
        control = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(control)
        for argv, expected in [(['control.py'], 0.2), (['control.py', '0.75'], 0.75)]:
            with patch.object(m, 'hypr', side_effect=compositor), \
                    patch.object(control.trackpoint, 'detect_device', return_value=TRACKPOINT), \
                    patch.object(control.sys, 'argv', argv), \
                    patch('sys.stdout', new_callable=io.StringIO) as output:
                control.main()
            self.assertEqual(json.loads(output.getvalue()), {'value': expected, 'device': TRACKPOINT})
        self.assertEqual(json.loads(m.read_state_file(m.STATE))['devices'][TRACKPOINT]['settings'],
                         {'sensitivity': 0.75})


if __name__ == '__main__':
    unittest.main()
