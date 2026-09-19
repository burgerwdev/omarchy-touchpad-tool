"""Gesture adoption, isolation, rollback and interrupted-write recovery."""
import json
import os
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import gestures as g

BINDING = 'hl.gesture({ fingers = 3, direction = "horizontal", action = "workspace" })'
INPUT = '-- Personal input\nhl.config({ input = { touchpad = { natural_scroll = false } } })\n' + BINDING + '\n'

class GestureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        for name, value in [('INPUT', root/'input.lua'), ('JOURNAL', root/'gestures.pending.json'), ('BACKUP', root/'original.txt')]:
            p = patch.object(g, name, value); p.start(); self.addCleanup(p.stop)
        g.INPUT.write_text(INPUT)
        self.settings = dict(enabled=True, fingers=3, distance=300, invert=False, overview=False)
        p = patch.object(g, 'companion_status', return_value=dict(installed=True, reachable=False, protocolCompatible=False, rendered=False)); p.start(); self.addCleanup(p.stop)
        self.provider_patch = patch.object(g, "hymission_status", return_value=dict(available=False, version="", message="HyMission is not loaded")); self.provider_patch.start(); self.addCleanup(self.provider_patch.stop)
        self.environment_patch = patch.object(g, 'check_environment'); self.environment_patch.start(); self.addCleanup(self.environment_patch.stop)
        p = patch.object(g, 'runtime_settings', return_value=dict(distance=300, invert=False)); p.start(); self.addCleanup(p.stop)
        self.calls = []
        def hypr(*args):
            self.calls.append(args)
            return '' if args[0] == 'configerrors' else 'ok'
        p = patch.object(g.core, 'hypr', side_effect=hypr); p.start(); self.addCleanup(p.stop)

    def stow_config(self, layout):
        home = Path(self.temp.name) / layout
        target = home / '.dotfiles/hypr/.config/hypr/input.lua'
        target.parent.mkdir(parents=True)
        target.write_text(INPUT)
        config = home / '.config/hypr'
        if layout == 'config-directory':
            config.parent.symlink_to('.dotfiles/hypr/.config', target_is_directory=True)
        elif layout == 'hypr-directory':
            config.parent.mkdir()
            config.symlink_to('../.dotfiles/hypr/.config/hypr', target_is_directory=True)
        else:
            config.mkdir(parents=True)
            (config / 'input.lua').symlink_to(os.path.relpath(target, config))
        return config, target

    def test_stow_config_reads_applies_and_restores_without_replacing_links(self):
        self.environment_patch.stop()
        for layout in ('file', 'hypr-directory', 'config-directory'):
            with self.subTest(layout=layout):
                config, target = self.stow_config(layout)
                link = config / 'input.lua' if layout == 'file' else (
                    config if layout == 'hypr-directory' else config.parent)
                before_link = os.readlink(link)
                with patch.object(g, 'CONFIG', config), patch.object(g, 'INPUT', config / 'input.lua'):
                    g.change(self.settings)
                    self.assertTrue(g.inspect(target.read_text())['managed'])
                    self.assertTrue(link.is_symlink())
                    self.assertEqual(os.readlink(link), before_link)
                    g.restore()
                    self.assertEqual(target.read_text(), INPUT)
                    self.assertEqual(os.readlink(link), before_link)

    def test_stow_linked_config_conflicts_are_still_detected(self):
        self.environment_patch.stop()
        config, target = self.stow_config('file')
        other = target.parent / 'bindings.lua'
        other.write_text(BINDING + '\n')
        (config / 'bindings.lua').symlink_to(other)
        with patch.object(g, 'CONFIG', config), patch.object(g, 'INPUT', config / 'input.lua'):
            with self.assertRaisesRegex(ValueError, 'another Hyprland file'):
                g.change(self.settings)
        self.assertEqual(target.read_text(), INPUT)
        self.assertFalse(g.JOURNAL.exists())

    def test_stow_nested_directory_conflicts_and_alias_extensions(self):
        self.environment_patch.stop()
        config, target = self.stow_config('file')
        nested = target.parent / 'extra'
        nested.mkdir()
        (config / 'extra').symlink_to(nested, target_is_directory=True)
        (nested / 'back').symlink_to(config, target_is_directory=True)
        extensionless = target.parent / 'bindings'
        extensionless.write_text(BINDING + '\n')
        (nested / 'bindings.lua').symlink_to(extensionless)
        with patch.object(g, 'CONFIG', config), patch.object(g, 'INPUT', config / 'input.lua'):
            with self.assertRaisesRegex(ValueError, 'another Hyprland file'):
                g.change(self.settings)
            extensionless.write_text('-- no gestures\n')
            g.change(self.settings)  # The directory cycle must terminate.
            g.restore()
        self.assertEqual(target.read_text(), INPUT)

    def test_stow_retarget_before_apply_refuses_even_identical_content(self):
        config, target = self.stow_config('file')
        alternate = target.with_name('alternate.lua')
        alternate.write_text(INPUT)
        inspect = g.inspect
        def retarget(source):
            status = inspect(source)
            g.INPUT.unlink()
            g.INPUT.symlink_to(alternate)
            return status
        with patch.object(g, 'INPUT', config / 'input.lua'), patch.object(g, 'inspect', side_effect=retarget):
            with self.assertRaisesRegex(ValueError, 'target changed'):
                g.change(self.settings)
        self.assertEqual(target.read_text(), INPUT)
        self.assertEqual(alternate.read_text(), INPUT)
        self.assertFalse(g.JOURNAL.exists())

    def test_stow_retarget_during_reload_keeps_journal_and_new_target_untouched(self):
        config, target = self.stow_config('file')
        alternate = target.with_name('alternate.lua')
        alternate.write_text(INPUT)
        def retarget():
            # Identical content must not authorize replay into a different file.
            alternate.write_text(target.read_text())
            g.INPUT.unlink()
            g.INPUT.symlink_to(alternate)
        with patch.object(g, 'INPUT', config / 'input.lua'):
            with patch.object(g, 'reload_checked', side_effect=retarget):
                with self.assertRaisesRegex(RuntimeError, 'recovery pending.*target changed'):
                    g.change(self.settings)
            after = target.read_text()
            self.assertNotEqual(after, INPUT)
            self.assertEqual(alternate.read_text(), after)
            self.assertTrue(g.JOURNAL.exists())
            g.INPUT.unlink()
            g.INPUT.symlink_to(target)
            g.recover()
            self.assertEqual(target.read_text(), INPUT)
            self.assertEqual(alternate.read_text(), after)
            self.assertTrue(g.INPUT.is_symlink())
            self.assertFalse(g.JOURNAL.exists())

    def test_stow_unrelated_dangling_links_do_not_block_apply(self):
        self.environment_patch.stop()
        config, target = self.stow_config('file')
        (config / 'wallpapers').symlink_to('unmounted/wallpapers', target_is_directory=True)
        (config / 'old.conf.bak').symlink_to(target.parent / 'removed-theme.conf')
        with patch.object(g, 'CONFIG', config), patch.object(g, 'INPUT', config / 'input.lua'):
            status = g.inspect(target.read_text())
            self.assertTrue(status['can_edit'], status['message'])
            g.change(self.settings)
            g.restore()
        self.assertEqual(target.read_text(), INPUT)
        self.assertTrue((config / 'wallpapers').is_symlink())
        self.assertTrue((config / 'old.conf.bak').is_symlink())

    def test_stow_missing_config_links_still_block_apply(self):
        self.environment_patch.stop()
        config, target = self.stow_config('file')
        for suffix in ('.lua', '.conf'):
            with self.subTest(suffix=suffix):
                missing = config / ('bindings' + suffix)
                missing.symlink_to(target.parent / 'removed-bindings')
                with patch.object(g, 'CONFIG', config), patch.object(g, 'INPUT', config / 'input.lua'):
                    self.assertFalse(g.inspect(target.read_text())['can_edit'])
                    with self.assertRaises(ValueError):
                        g.change(self.settings)
                self.assertEqual(target.read_text(), INPUT)
                self.assertFalse(g.JOURNAL.exists())
                missing.unlink()

    def test_stow_retarget_during_recovery_reload_preserves_journal(self):
        config, target = self.stow_config('file')
        alternate = target.with_name('alternate.lua')
        after = INPUT + '-- pending edit\n'
        target.write_text(after)
        alternate.write_text(after)
        journal = json.dumps(dict(version=2, before=INPUT, after=after, target=str(target)))
        g.JOURNAL.write_text(journal)

        def retarget():
            g.INPUT.unlink()
            g.INPUT.symlink_to(alternate)

        with patch.object(g, 'INPUT', config / 'input.lua'):
            with patch.object(g, 'reload_checked', side_effect=retarget):
                with self.assertRaisesRegex(ValueError, 'target changed'):
                    g.recover()
            self.assertEqual(g.JOURNAL.read_text(), journal)
            self.assertEqual(target.read_text(), INPUT)
            self.assertEqual(alternate.read_text(), after)
            g.INPUT.unlink()
            g.INPUT.symlink_to(target)
            g.recover()
            self.assertFalse(g.JOURNAL.exists())
            self.assertEqual(target.read_text(), INPUT)
            self.assertEqual(alternate.read_text(), after)
            self.assertTrue(g.INPUT.is_symlink())

    def test_legacy_recovery_journal_refuses_new_stow_target(self):
        config, target = self.stow_config('file')
        after = INPUT + '-- pending edit\n'
        journal = json.dumps(dict(version=1, before=INPUT, after=after))
        g.JOURNAL.write_text(journal)
        target.write_text(after)
        with patch.object(g, 'INPUT', config / 'input.lua'):
            with self.assertRaisesRegex(ValueError, 'target changed'):
                g.recover()
            self.assertTrue(g.INPUT.is_symlink())
        self.assertEqual(target.read_text(), after)
        self.assertEqual(g.JOURNAL.read_text(), journal)

    def test_stow_reload_failure_restores_dotfile_and_link(self):
        config, target = self.stow_config('file')
        with patch.object(g, 'INPUT', config / 'input.lua'):
            with patch.object(g, 'reload_checked', side_effect=[RuntimeError('reload failed'), None]):
                with self.assertRaisesRegex(RuntimeError, 'reload failed'):
                    g.change(self.settings)
            self.assertTrue(g.INPUT.is_symlink())
        self.assertEqual(target.read_text(), INPUT)
        self.assertFalse(g.JOURNAL.exists())

    def test_stow_unsafe_or_broken_targets_do_not_write(self):
        for kind in ('loop', 'dangling', 'shared-directory', 'shared-file', 'fifo', 'hardlink'):
            with self.subTest(kind=kind):
                config, target = self.stow_config(kind)
                link = config / 'input.lua'
                if kind in ('loop', 'dangling'):
                    link.unlink()
                    link.symlink_to('input.lua' if kind == 'loop' else 'missing.lua')
                elif kind == 'shared-directory':
                    target.parent.chmod(0o777)
                elif kind == 'shared-file':
                    target.chmod(0o666)
                elif kind == 'fifo':
                    target.unlink()
                    os.mkfifo(target)
                else:
                    os.link(target, target.with_name('alias.lua'))
                with patch.object(g, 'INPUT', link):
                    with self.assertRaises((ValueError, OSError)):
                        g.change(self.settings)
                self.assertTrue(link.is_symlink())
                self.assertFalse(g.JOURNAL.exists())
                if kind != 'fifo':
                    self.assertEqual(target.read_text(), INPUT)

    def test_stow_resolution_closes_directory_descriptors(self):
        config, target = self.stow_config('file')
        before = len(os.listdir('/proc/self/fd'))
        for _ in range(100):
            self.assertEqual(g.config_target(config / 'input.lua'), target)
        self.assertEqual(len(os.listdir('/proc/self/fd')), before)
        (config / 'input.lua').unlink()
        (config / 'input.lua').symlink_to('input.lua')
        for _ in range(100):
            with self.assertRaisesRegex(ValueError, 'symlink loop'):
                g.config_target(config / 'input.lua')
        self.assertEqual(len(os.listdir('/proc/self/fd')), before)

    @patch("platform.machine", return_value="x86_64")
    def test_provider_probe_is_optional_and_checks_gesture_api(self, _machine):
        self.provider_patch.stop()
        with patch.object(g.core, 'hypr', return_value='[]'):
            self.assertFalse(g.hymission_status()['available'])
        with patch.object(g.core, 'hypr', side_effect=['[{"name":"hymission","version":"0.7.0"}]', 'ok']):
            self.assertTrue(g.hymission_status()['available'])
        for failure in [RuntimeError('no API'), subprocess.TimeoutExpired('hyprctl', 4)]:
            with patch.object(g.core, 'hypr', side_effect=failure):
                self.assertFalse(g.hymission_status()['available'])
                self.assertTrue(g.inspect(INPUT)['can_edit'])

    def test_loaded_provider_on_arm64_cannot_enable_overview_or_change_input(self):
        self.provider_patch.stop()
        with patch("platform.machine", return_value="aarch64"), patch.object(
                g.core, 'hypr', side_effect=lambda *args: '[{"name":"hymission","version":"0.7.0"}]' if args[0] == 'plugin' else 'ok'):
            status = g.hymission_status()
            self.assertFalse(status['available'])
            self.assertFalse(status['supported'])
            self.assertIn('ARM64', status['message'])
            self.assertTrue(g.inspect(INPUT)['can_edit'])
            with self.assertRaisesRegex(ValueError, 'ARM64'):
                g.change(dict(self.settings, overview=True))
        self.assertEqual(g.INPUT.read_text(), INPUT)
        self.assertFalse(g.JOURNAL.exists())

    def test_provider_loss_during_reload_rolls_back(self):
        yes = dict(available=True, version='0.7.0', message='')
        no = dict(available=False, version='', message='HyMission missing')
        with patch.object(g, 'hymission_status', side_effect=[yes, no]):
            with self.assertRaisesRegex(RuntimeError, 'became unavailable'):
                g.change(dict(self.settings, overview=True))
        self.assertEqual(g.INPUT.read_text(), INPUT)
        self.assertFalse(g.JOURNAL.exists())

    def test_overview_guard_cannot_hide_manually_modified_or_inactive_code(self):
        with patch.object(g, 'hymission_status', return_value=dict(available=True, version='0.7.0', message='')):
            g.change(dict(self.settings, overview=True))
        valid = g.INPUT.read_text()
        for source in ['if false then\n' + valid + 'end\n',
                       'local text = [=[\n' + valid + ']=]\n',
                       valid.replace('args = "forceall"', 'args = "onlycurrentworkspace"')]:
            self.assertFalse(g.inspect(source)['can_restore'])

    def test_overview_requires_loaded_provider_before_writing(self):
        with self.assertRaisesRegex(ValueError, 'HyMission'):
            g.change(dict(self.settings, overview=True))
        self.assertEqual(g.INPUT.read_text(), INPUT)
        self.assertFalse(g.JOURNAL.exists())

    def test_overview_lua_has_one_horizontal_binding_with_optional_provider(self):
        settings = dict(self.settings, overview=True)
        with patch.object(g, 'hymission_status', return_value=dict(available=True, version='0.7.0', message='HyMission loaded')):
            g.change(settings)
        text = g.INPUT.read_text()
        self.assertEqual(g.inspect(text)['settings'], dict(settings, overview_provider='hymission'))
        for loaded in (False, True):
            lua = 'local native, plugin = {}, {}\nhl = {config=function() end, device=function() end, plugin={}, gesture=function(d) table.insert(native,d) end}\n'
            if loaded:
                lua += 'hl.plugin.hymission={gesture=function(d) table.insert(plugin,d) end}\n'
            lua += text
            lua += ('\nassert(#native == 0 and #plugin == 2)\nassert(plugin[1].direction == "horizontal" and plugin[1].action == "workspace")\nassert(plugin[2].direction == "vertical" and plugin[2].action == "toggle" and plugin[2].args == "forceall")' if loaded else '\nassert(#native == 1 and #plugin == 0 and native[1].direction == "horizontal")')
            subprocess.run(['lua', '-'], input=lua, text=True, capture_output=True, check=True)
        # Losing the optional provider must still allow disabling and restoring.
        g.change(self.settings)
        g.restore()
        self.assertEqual(g.INPUT.read_text(), INPUT)

    def test_manual_vertical_gesture_is_not_replaced(self):
        source = INPUT + 'hl.gesture({ fingers = 3, direction = "up", action = "fullscreen" })\n'
        g.INPUT.write_text(source)
        with patch.object(g, 'hymission_status', return_value=dict(available=True, version='0.7.0', message='')):
            with self.assertRaisesRegex(ValueError, 'vertical|overview'):
                g.change(dict(self.settings, overview=True))
        self.assertEqual(g.INPUT.read_text(), source)

    def test_legacy_schema_bytes_are_preserved_on_read_and_restore(self):
        # Literal historical blocks: regeneration cannot define its own fixture.
        for version, extra, body in [
            (2, '', BINDING + '\n'),
            (3, ', "overview": true',
             'if hl.plugin.hymission and hl.plugin.hymission.gesture then\n'
             '  hl.plugin.hymission.gesture({ fingers = 3, direction = "horizontal", action = "workspace" })\n'
             '  hl.plugin.hymission.gesture({ fingers = 3, direction = "vertical", action = "toggle", args = "forceall" })\n'
             'else\n  ' + BINDING + '\nend\n')]:
            metadata = ('-- {"original": "", "separator": "", "settings": {"distance": 300, '
                        '"enabled": true, "fingers": 3, "invert": false' + extra +
                        '}, "version": ' + str(version) + '}\n')
            fixture = (g.BEGIN + metadata + body +
                       'hl.config({ gestures = { workspace_swipe_distance = 300, workspace_swipe_invert = false } })\n' + g.END)
            source = '-- Before\n' + fixture + '-- After\n'
            g.INPUT.write_text(source)
            parsed = g.parse(source)
            self.assertEqual(g.block(parsed[2], parsed[3], version=version), fixture)
            g.inspect(source)
            self.assertEqual(g.INPUT.read_text(), source)
            g.restore()
            self.assertEqual(g.INPUT.read_text(), '-- Before\n-- After\n')

    def test_schema_two_block_migrates_and_restores_exact_original(self):
        legacy = {key:value for key,value in self.settings.items() if key != 'overview'}
        oldblock = g.block(legacy, BINDING + '\n', version=2)
        source = INPUT.replace(BINDING + '\n', g.ANCHOR) + oldblock
        g.INPUT.write_text(source)
        self.assertFalse(g.inspect(source)['settings']['overview'])
        g.change(legacy)
        self.assertEqual(g.inspect(g.INPUT.read_text())['settings'], dict(self.settings, overview_provider='hymission'))
        g.restore()
        self.assertEqual(g.INPUT.read_text(), INPUT)

    def test_companion_provider_keeps_native_horizontal_and_explicit_callbacks(self):
        settings = dict(self.settings, overview=True, overview_provider='trackpad-plus')
        with patch('platform.machine', return_value='aarch64'):
            g.change(settings)
        source = g.INPUT.read_text()
        self.assertEqual(g.parse(source)[2], settings)
        self.assertNotIn('hl.plugin.hymission', source)
        lua = ('local native, commands = {}, {}\n'
               'hl={config=function() end, layer_rule=function(r) assert(r.match.namespace == "^trackpad-plus-overview$" and r.no_anim and r.animation == "none") end, gesture=function(d) table.insert(native,d) end, '
               'exec_cmd=function(c) table.insert(commands,c) end}\n' + source +
               '\nassert(#native == 3 and native[1].direction == "horizontal" and native[1].action == "workspace")'
               '\nassert(native[2].direction == "up" and native[3].direction == "down")'
               '\nassert(#commands == 0 and type(native[2].action) == "table")'
               '\nnative[2].action.start({})'
               '\nassert(#commands == 1 and commands[1] == ' + json.dumps(g.COMPANION_COMMAND + 'open') + ', "up must open before finger release")'
               '\nassert(native[2].action.finish == nil and native[2].action.update == nil, "up must not reopen or cancel at release")'
               '\nnative[3].action.finish({cancelled=true})'
               '\nassert(#commands == 1, "cancelled down must not close")'
               '\nassert(native[3].action.start == nil)\nnative[3].action.finish({cancelled=false})'
               '\nassert(#commands == 2 and commands[2] == ' + json.dumps(g.COMPANION_COMMAND + 'close') + ')')
        subprocess.run(['lua', '-'], input=lua, text=True, capture_output=True, check=True)
        self.assertIn('"version": 7', source)
        g.restore()
        self.assertEqual(g.INPUT.read_text(), INPUT)

    def test_schema_four_literal_read_migrate_and_restore(self):
        fixture = r'''-- BEGIN local.touchpad-tool gestures
-- {"original": "hl.gesture({ fingers = 3, direction = \"horizontal\", action = \"workspace\" })\n", "separator": "", "settings": {"distance": 300, "enabled": true, "fingers": 3, "invert": false, "overview": true, "overview_provider": "trackpad-plus"}, "version": 4}
hl.gesture({ fingers = 3, direction = "horizontal", action = "workspace" })
hl.gesture({ fingers = 3, direction = "up", action = function() hl.exec_cmd("python3 -B \"${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/local.touchpad-tool/overview-control.py\" open") end })
hl.gesture({ fingers = 3, direction = "down", action = function() hl.exec_cmd("python3 -B \"${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/local.touchpad-tool/overview-control.py\" close") end })
hl.config({ gestures = { workspace_swipe_distance = 300, workspace_swipe_invert = false } })
-- END local.touchpad-tool gestures
'''
        historical = INPUT.replace(BINDING + '\n', g.ANCHOR) + fixture
        for mode in ('restore', 'migrate', 'failed-migration'):
            g.INPUT.write_text(historical)
            parsed = g.parse(historical)
            self.assertEqual(g.block(parsed[2], parsed[3], version=4), fixture)
            self.assertTrue(g.inspect(historical)['can_restore'])
            self.assertEqual(g.INPUT.read_text(), historical)
            if mode == 'migrate':
                g.change(parsed[2])
                self.assertIn('"version": 7', g.INPUT.read_text())
                self.assertEqual(g.parse(g.INPUT.read_text())[3], BINDING + '\n')
            elif mode == 'failed-migration':
                with patch.object(g, 'reload_checked', side_effect=[RuntimeError('unsupported callback API'), None]):
                    with self.assertRaisesRegex(RuntimeError, 'unsupported callback API'):
                        g.change(parsed[2])
                self.assertEqual(g.INPUT.read_text(), historical)
                self.assertFalse(g.JOURNAL.exists())
            g.restore()
            self.assertEqual(g.INPUT.read_text(), INPUT)

    def test_schema_five_literal_preserved_until_explicit_edit(self):
        fixture = r'''-- BEGIN local.touchpad-tool gestures
-- {"original": "", "separator": "", "settings": {"distance": 300, "enabled": true, "fingers": 3, "invert": false, "overview": true, "overview_provider": "trackpad-plus"}, "version": 5}
hl.gesture({ fingers = 3, direction = "horizontal", action = "workspace" })
hl.gesture({ fingers = 3, direction = "up", action = { start = function() hl.exec_cmd("python3 -B \"${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/local.touchpad-tool/overview-control.py\" start") end, finish = function(event) if not event.cancelled then hl.exec_cmd("python3 -B \"${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/local.touchpad-tool/overview-control.py\" open") end end } })
hl.gesture({ fingers = 3, direction = "down", action = { finish = function(event) if not event.cancelled then hl.exec_cmd("python3 -B \"${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/local.touchpad-tool/overview-control.py\" close") end end } })
hl.config({ gestures = { workspace_swipe_distance = 300, workspace_swipe_invert = false } })
-- END local.touchpad-tool gestures
'''
        g.INPUT.write_text(fixture)
        settings = g.parse(fixture)[2]
        self.assertEqual(g.block(settings, '', version=5), fixture)
        self.assertTrue(g.inspect(fixture)['can_restore'])
        self.assertEqual(g.INPUT.read_text(), fixture)
        with patch.object(g, 'reload_checked', side_effect=[RuntimeError('failed reload'), None]):
            with self.assertRaisesRegex(RuntimeError, 'failed reload'):
                g.change(settings)
        self.assertEqual(g.INPUT.read_text(), fixture)
        g.change(settings)
        self.assertIn('"version": 7', g.INPUT.read_text())
        self.assertEqual(g.parse(g.INPUT.read_text())[2], settings)
        g.restore()
        self.assertEqual(g.INPUT.read_text(), '')

    def test_companion_callbacks_preserve_spaces_without_shell_injection(self):
        source = g.COMPANION_COMMAND + 'open'
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / 'config with $(touch SHOULD_NOT_EXIST) spaces'
            script = base / 'omarchy/plugins/local.touchpad-tool/overview-control.py'
            script.parent.mkdir(parents=True)
            script.write_text('import sys; print(sys.argv[1])')
            import os
            result = subprocess.run(['sh', '-c', source], env=dict(os.environ, XDG_CONFIG_HOME=str(base)),
                                    text=True, capture_output=True, check=True, cwd=temporary)
            self.assertEqual(result.stdout.strip(), 'open')
            self.assertFalse((Path(temporary) / 'SHOULD_NOT_EXIST').exists())

    def test_companion_missing_or_conflicting_vertical_does_not_write(self):
        settings = dict(self.settings, overview=True, overview_provider='trackpad-plus')
        with patch.object(g, 'companion_status', return_value=dict(installed=False, message='Install overview')):
            with self.assertRaisesRegex(ValueError, 'Install overview'):
                g.change(settings)
        self.assertEqual(g.INPUT.read_text(), INPUT)
        vertical = 'hl.gesture({ fingers = 3, direction = "up", action = "fullscreen" })\n'
        g.INPUT.write_text(INPUT + vertical)
        with self.assertRaisesRegex(ValueError, 'vertical'):
            g.change(settings)
        self.assertEqual(g.INPUT.read_text(), INPUT + vertical)

    def test_provider_switch_and_failed_reload_restore_exact_previous_block(self):
        with patch.object(g, 'hymission_status', return_value=dict(available=True)):
            g.change(dict(self.settings, overview=True))
        previous = g.INPUT.read_text()
        with patch.object(g, 'reload_checked', side_effect=[RuntimeError('failed switch'), None]):
            with self.assertRaisesRegex(RuntimeError, 'failed switch'):
                g.change(dict(self.settings, overview=True, overview_provider='trackpad-plus'))
        self.assertEqual(g.INPUT.read_text(), previous)
        g.change(dict(self.settings, overview=True, overview_provider='trackpad-plus'))
        g.change(dict(self.settings, overview=True))  # Older callers retain the saved provider.
        self.assertEqual(g.parse(g.INPUT.read_text())[2]['overview_provider'], 'trackpad-plus')
        g.restore()
        self.assertEqual(g.INPUT.read_text(), INPUT)

    def test_schema_six_preserves_bytes_until_explicit_edit(self):
        fixture = '-- BEGIN local.touchpad-tool gestures\n-- {"original": "", "separator": "", "settings": {"distance": 300, "enabled": true, "fingers": 3, "invert": false, "overview": true, "overview_provider": "trackpad-plus"}, "version": 6}\nhl.gesture({ fingers = 3, direction = "horizontal", action = "workspace" })\nhl.gesture({ fingers = 3, direction = "up", action = { start = function() hl.exec_cmd("python3 -B \\"${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/local.touchpad-tool/overview-control.py\\" open") end } })\nhl.gesture({ fingers = 3, direction = "down", action = { finish = function(event) if not event.cancelled then hl.exec_cmd("python3 -B \\"${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/local.touchpad-tool/overview-control.py\\" close") end end } })\nhl.config({ gestures = { workspace_swipe_distance = 300, workspace_swipe_invert = false } })\n-- END local.touchpad-tool gestures\n'
        g.INPUT.write_text(fixture)
        parsed = g.parse(fixture)
        self.assertEqual(g.block(parsed[2], parsed[3], version=6), fixture)
        self.assertNotIn('hl.layer_rule', fixture)
        g.inspect(fixture)
        self.assertEqual(g.INPUT.read_text(), fixture)
        g.change(parsed[2])
        source = g.INPUT.read_text()
        self.assertIn('"version": 7', source)
        self.assertIn('namespace = "^trackpad-plus-overview$"', source)
        self.assertIn('no_anim = true', source)
        g.change(dict(parsed[2], overview=False))
        self.assertNotIn('hl.layer_rule', g.INPUT.read_text())

    def test_schema_five_rejects_modified_callback_or_provider(self):
        g.change(dict(self.settings, overview=True, overview_provider='trackpad-plus'))
        source = g.INPUT.read_text()
        for modified in [source.replace('hl.exec_cmd', 'os.execute'),
                         source.replace('overview-control.py', 'other.py'),
                         source.replace('if not event.cancelled then', 'if true then'),
                         source.replace('finish = function', 'end = function'),
                         source.replace('"trackpad-plus"', '"unknown"'),
                         'if false then\n' + source + 'end\n']:
            g.INPUT.write_text(modified)
            with self.assertRaises(ValueError):
                g.restore()
            self.assertEqual(g.INPUT.read_text(), modified)

    def test_preview_and_status_never_take_settings_lock_or_edit_config(self):
        for action, operation in [('preview', 'open'), ('overview-status', 'status')]:
            with patch.object(g.sys, 'argv', ['gestures.py', action]), \
                    patch.object(g.core, 'state_lock', side_effect=AssertionError('settings lock taken')), \
                    patch.object(g, 'companion_status', return_value=dict(installed=True)) as status, \
                    patch('builtins.print'):
                g.main()
                status.assert_called_once_with(operation)
        self.assertEqual(g.INPUT.read_text(), INPUT)
        self.assertFalse(g.JOURNAL.exists())

    def test_adopts_existing_binding_once_and_preserves_other_input(self):
        before = g.inspect(INPUT)
        self.assertFalse(before['managed'])
        self.assertTrue(before['settings']['enabled'])
        self.assertEqual(before['settings']['fingers'], 3)
        g.change(self.settings)
        result = g.INPUT.read_text()
        self.assertEqual(g.masked(result).count('hl.gesture('), 1)
        self.assertIn('natural_scroll = false', result)
        self.assertTrue(g.inspect(result)['managed'])
        self.assertEqual(g.BACKUP.read_text(), INPUT)
        g.change(dict(self.settings, fingers=4))
        self.assertEqual(g.masked(g.INPUT.read_text()).count('hl.gesture('), 1)
        g.restore()
        self.assertEqual(g.INPUT.read_text(), INPUT)

    def test_disabled_binding_and_restore_preserve_later_unrelated_edits(self):
        g.change(dict(self.settings, enabled=False))
        self.assertNotIn('\nhl.gesture(', g.INPUT.read_text())
        g.INPUT.write_text(g.INPUT.read_text() + '\n-- Later input notes\n')
        g.restore()
        self.assertEqual(g.INPUT.read_text(), INPUT + '\n-- Later input notes\n')

    def test_rejects_ambiguous_bindings_without_writing(self):
        for source in [INPUT + BINDING, 'if true then\n' + BINDING + '\nend',
                       'local gesture = hl.gesture\ngesture({})',
                       'hl.gesture({ fingers=3, direction="swipe", action="workspace" })']:
            with self.subTest(source=source):
                g.INPUT.write_text(source)
                self.assertFalse(g.inspect(source)['can_edit'])
                with self.assertRaises(ValueError): g.change(self.settings)
                self.assertEqual(g.INPUT.read_text(), source)

    def test_ignores_commented_gestures_and_keeps_vertical_bindings(self):
        source = '--[[\n' + BINDING + '\n]]\n-- ' + BINDING + '\n'
        self.assertFalse(g.inspect(source)['settings']['enabled'])
        source = INPUT + 'hl.gesture({ fingers = 3, direction = "up", action = "fullscreen" })\n'
        g.INPUT.write_text(source)
        g.change(self.settings)
        self.assertIn('action = "fullscreen"', g.INPUT.read_text())

    def test_rejects_invalid_settings_and_modified_managed_block(self):
        for key, value in [('distance', 0), ('distance', 2001), ('fingers', 2), ('enabled', 1), ('invert', 'false')]:
            with self.assertRaises(ValueError): g.change(dict(self.settings, **{key:value}))
            self.assertEqual(g.INPUT.read_text(), INPUT)
        g.change(self.settings)
        g.INPUT.write_text(g.INPUT.read_text().replace('distance = 300', 'distance = 301'))
        self.assertFalse(g.inspect(g.INPUT.read_text())['can_edit'])

    def test_managed_block_follows_later_options_and_returns_to_end_on_apply(self):
        later = 'hl.config({ gestures = { workspace_swipe_distance = 900 } })\n'
        source = INPUT + later
        g.INPUT.write_text(source)
        g.change(self.settings)
        self.assertGreater(g.INPUT.read_text().index(g.BEGIN), g.INPUT.read_text().index(later))
        added = '-- Later notes\n' + later
        g.INPUT.write_text(g.INPUT.read_text() + added)
        g.change(self.settings)
        self.assertTrue(g.INPUT.read_text().endswith(g.END))
        g.restore()
        self.assertEqual(g.INPUT.read_text(), source + added)

    def test_long_string_gesture_is_not_adopted(self):
        source = 'local example = [=[\n' + BINDING + '\n]=]\n' + INPUT
        g.INPUT.write_text(source)
        g.change(self.settings)
        self.assertIn('local example = [=[\n' + BINDING + '\n]=]', g.INPUT.read_text())
        g.restore()
        self.assertEqual(g.INPUT.read_text(), source)

    def test_rejects_inactive_or_nested_managed_block(self):
        g.change(self.settings)
        valid = g.INPUT.read_text()
        for source in ['if false then\n' + valid + 'end\n',
                       'local example = [=[\n' + valid + ']=]\n',
                       'local example = {\n' + valid + '}\n',
                       '--[=[\n' + valid + ']=]\n']:
            with self.subTest(source=source):
                self.assertFalse(g.inspect(source)['can_edit'])

    def test_restore_exact_text_without_final_newline(self):
        for source in [INPUT.rstrip('\n'), '-- Notes without newline', '']:
            with self.subTest(source=source):
                g.INPUT.write_text(source)
                g.change(self.settings)
                g.restore()
                self.assertEqual(g.INPUT.read_text(), source)

    def test_anchor_tampering_refuses_to_overwrite_manual_edits(self):
        g.change(self.settings)
        valid = g.INPUT.read_text()
        variants = [valid.replace(g.ANCHOR, ''), valid + g.ANCHOR,
                    valid.replace(g.ANCHOR, '') + g.ANCHOR,
                    valid.replace(g.ANCHOR, 'local text = [[\n' + g.ANCHOR + ']]\n')]
        for source in variants:
            with self.subTest(source=source):
                g.INPUT.write_text(source)
                with self.assertRaises(ValueError):
                    g.restore()
                self.assertEqual(g.INPUT.read_text(), source)

    def test_non_default_runtime_values_are_checked(self):
        settings = dict(self.settings, distance=725, invert=True)
        with patch.object(g, 'runtime_settings', return_value=dict(distance=725, invert=True)):
            g.change(settings)
        self.assertEqual(g.parse(g.INPUT.read_text())[2], dict(settings, overview_provider='hymission'))
        with patch.object(g, 'runtime_settings', return_value=dict(distance=725, invert=False)):
            with self.assertRaisesRegex(RuntimeError, 'do not match'):
                g.change(settings)
        self.assertEqual(g.parse(g.INPUT.read_text())[2], dict(settings, overview_provider='hymission'))

    def test_runtime_override_rolls_back(self):
        with patch.object(g, 'runtime_settings', return_value=dict(distance=900, invert=False)):
            with self.assertRaisesRegex(RuntimeError, 'override|match'):
                g.change(self.settings)
        self.assertEqual(g.INPUT.read_text(), INPUT)
        self.assertFalse(g.JOURNAL.exists())

    def test_external_gesture_conflict_and_missing_module(self):
        self.environment_patch.stop()
        with patch.object(g, 'CONFIG', g.INPUT.parent):
            other = g.INPUT.parent / 'other.lua'
            other.write_text(BINDING)
            with self.assertRaisesRegex(ValueError, 'another Hyprland file'):
                g.change(self.settings)
            self.assertEqual(g.INPUT.read_text(), INPUT)
            other.unlink()
            with patch.object(g.core, 'hypr', side_effect=RuntimeError('hypr.input unavailable')):
                with self.assertRaisesRegex(ValueError, 'unavailable'):
                    g.change(self.settings)
            self.assertEqual(g.INPUT.read_text(), INPUT)

    def test_external_conflict_keeps_restore_available(self):
        g.change(self.settings)
        with patch.object(g, 'check_environment', side_effect=ValueError('external conflict')):
            status = g.inspect(g.INPUT.read_text())
            self.assertFalse(status['can_edit'])
            self.assertTrue(status['can_restore'])
            g.restore()
        self.assertEqual(g.INPUT.read_text(), INPUT)

    def test_legacy_config_conflict_is_rejected_without_writes(self):
        self.environment_patch.stop()
        with patch.object(g, 'CONFIG', g.INPUT.parent):
            other = g.INPUT.parent / 'gestures.conf'
            other.write_text('# gesture = commented out\ngesture = 3, horizontal, workspace\n')
            with self.assertRaisesRegex(ValueError, 'another Hyprland file'):
                g.change(self.settings)
            self.assertEqual(g.INPUT.read_text(), INPUT)
            other.write_text('# gesture = commented out\n')
            g.check_environment()

    def test_failed_reload_and_rollback_keep_recovery_journal(self):
        with patch.object(g.core, 'hypr', side_effect=['', RuntimeError('reload failed'), RuntimeError('rollback failed')]):
            with self.assertRaisesRegex(RuntimeError, 'recovery pending.*rollback failed'):
                g.change(self.settings)
        self.assertEqual(g.INPUT.read_text(), INPUT)
        self.assertTrue(g.JOURNAL.exists())
        g.recover()
        self.assertFalse(g.JOURNAL.exists())

    def test_reload_failure_rolls_back_and_clears_journal(self):
        with patch.object(g.core, 'hypr', side_effect=['', RuntimeError('reload failed'), 'ok', '']):
            with self.assertRaisesRegex(RuntimeError, 'reload failed'): g.change(self.settings)
        self.assertEqual(g.INPUT.read_text(), INPUT)
        self.assertFalse(g.JOURNAL.exists())

    def test_config_errors_roll_back(self):
        with patch.object(g.core, 'hypr', side_effect=['', 'ok', 'duplicate gesture', 'ok', '']):
            with self.assertRaisesRegex(RuntimeError, 'duplicate gesture'): g.change(self.settings)
        self.assertEqual(g.INPUT.read_text(), INPUT)

    def test_recovery_restores_only_expected_file(self):
        g.JOURNAL.write_text(json.dumps(dict(version=1, before=INPUT, after='replacement')))
        g.INPUT.write_text('replacement')
        g.recover()
        self.assertEqual(g.INPUT.read_text(), INPUT)
        self.assertFalse(g.JOURNAL.exists())
        g.JOURNAL.write_text(json.dumps(dict(version=1, before=INPUT, after='replacement')))
        g.INPUT.write_text('manual edit')
        with self.assertRaisesRegex(ValueError, 'changed'): g.recover()
        self.assertEqual(g.INPUT.read_text(), 'manual edit')
        self.assertTrue(g.JOURNAL.exists())

if __name__ == '__main__': unittest.main()
