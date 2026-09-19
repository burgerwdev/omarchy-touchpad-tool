"""Device detection: one classification shared by the panel and both backends."""
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('devices', Path(__file__).with_name('devices.py'))
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)

TOUCHPAD = {'name': 'synaptics-tm3381-002'}
TRACKPOINT = {'name': 'tpps/2-elan-trackpoint'}
APPLE = {'name': 'apple-mtp-multi-touch'}
MOUSE = {'name': 'logitech-usb-receiver'}


class DetectTests(unittest.TestCase):
    def test_both_devices_show_both_tabs(self):
        found = d.detect([TOUCHPAD, TRACKPOINT, MOUSE])
        self.assertEqual(found['touchpads'], ['synaptics-tm3381-002'])
        self.assertEqual(found['trackpoints'], ['tpps/2-elan-trackpoint'])
        self.assertEqual(found['tabs'], ['trackpad', 'trackpoint'])
        self.assertEqual(found['default_tab'], 'trackpad')

    def test_touchpad_only_hides_the_trackpoint_tab(self):
        found = d.detect([APPLE, MOUSE])
        self.assertEqual(found['tabs'], ['trackpad'])
        self.assertEqual(found['trackpoints'], [])
        self.assertEqual(found['default_tab'], 'trackpad')

    def test_trackpoint_only_hides_the_trackpad_tab(self):
        found = d.detect([TRACKPOINT, MOUSE])
        self.assertEqual(found['tabs'], ['trackpoint'])
        self.assertEqual(found['touchpads'], [])
        self.assertEqual(found['default_tab'], 'trackpoint')

    def test_no_supported_devices_yields_no_tabs_and_no_error(self):
        found = d.detect([MOUSE])
        self.assertEqual(found['tabs'], [])
        self.assertEqual(found['default_tab'], '')
        self.assertEqual(found['touchpads'], [])
        self.assertEqual(found['trackpoints'], [])

    def test_trackpoint_is_never_grouped_as_a_touchpad(self):
        found = d.detect([TRACKPOINT])
        self.assertEqual(found['touchpads'], [])

    def test_touchpad_whose_name_contains_trackpad_is_kept(self):
        found = d.detect([{'name': 'apple-inc.-magic-trackpad'}, TRACKPOINT])
        self.assertEqual(found['tabs'], ['trackpad', 'trackpoint'])
        self.assertIn('apple-inc.-magic-trackpad', found['touchpads'])

    def test_hyprctl_output_is_read_once(self):
        calls = []

        def fake_hypr(*args):
            calls.append(args)
            return json.dumps({'mice': [TOUCHPAD, TRACKPOINT]})

        out = io.StringIO()
        with patch.object(d.trackpads, 'hypr', fake_hypr), patch('sys.stdout', out):
            status = d.report()
        self.assertEqual(calls, [('devices', '-j')])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(out.getvalue())['tabs'], ['trackpad', 'trackpoint'])

    def test_hyprctl_failure_reports_an_error_without_crashing(self):
        out = io.StringIO()
        with patch.object(d.trackpads, 'hypr', side_effect=RuntimeError('hyprctl missing')), \
                patch('sys.stdout', out):
            status = d.report()
        self.assertEqual(status, 1)
        self.assertIn('hyprctl missing', json.loads(out.getvalue())['error'])


if __name__ == '__main__':
    unittest.main()
