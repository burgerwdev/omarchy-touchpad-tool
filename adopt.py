#!/usr/bin/env python3
"""Detect other touchpad/TrackPoint tools and migrate their settings.

  adopt.py status              report other plugins and legacy blocks that affect these devices
  adopt.py backup              copy every file this plugin owns or edits into a timestamped folder
  adopt.py import              back up first, then move legacy settings into this plugin's state
  adopt.py disable <plugin-id> back up first, then disable that plugin

Disabling is the strongest action taken here: this tool never removes another
plugin, and the panel tells the user the command to uninstall it themselves.
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
import gestures  # noqa: E402  (input.lua target resolution, same stow/symlink rules)
import trackpads  # noqa: E402
import trackpoint  # noqa: E402

PLUGIN_ID = 'local.touchpad-tool'
REMOVE_HINT = 'omarchy plugin remove'
CONFIG = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'hypr'
INPUT = CONFIG / 'input.lua'
BINDINGS = CONFIG / 'bindings.lua'
BACKUPS = trackpads.STATE_ROOT / 'omarchy/touchpad-tool/backups'
MIDDLE_STORE = trackpads.STATE_ROOT / 'omarchy/trackpoint/middle.json'
SIMILAR = re.compile(r'touchpad|trackpad|trackpoint', re.I)
# Blocks written by the tools this plugin replaces.
LEGACY_MIDDLE = ('-- BEGIN io.github.artmoreno.trackpoint middle button',
                 '-- END io.github.artmoreno.trackpoint middle button')
LEGACY_DEVICE = ('-- BEGIN io.github.artmoreno.trackpoint device',
                 '-- END io.github.artmoreno.trackpoint device')
LEGACY_GESTURES = ('-- BEGIN Trackpad Plus gestures', '-- END Trackpad Plus gestures')
LEGACY_ANCHOR = '-- Trackpad Plus original gesture location'
MIDDLE_MARKERS = ('-- BEGIN local.touchpad-tool middle button',
                  '-- END local.touchpad-tool middle button')
GESTURE_MARKERS = ('-- BEGIN local.touchpad-tool gestures', '-- END local.touchpad-tool gestures')
ANCHOR = '-- local.touchpad-tool original gesture location'


def owned_files():
    """Every file this plugin writes, so a backup is never partial."""
    return [trackpads.STATE, trackpads.GENERATED, MIDDLE_STORE, INPUT, BINDINGS]


def other_plugins():
    """Installed plugins that also manage these devices, this one excluded."""
    try:
        out = subprocess.run(['omarchy', 'plugin', 'list', '--json'],
                             capture_output=True, text=True, timeout=20, check=True).stdout
        plugins = json.loads(out)
    except Exception:
        return []
    found = []
    for plugin in plugins:
        if plugin.get('id') == PLUGIN_ID:
            continue
        if SIMILAR.search(str(plugin.get('id', '')) + ' ' + str(plugin.get('name', ''))):
            found.append({'id': plugin.get('id', ''), 'name': plugin.get('name', ''),
                          'enabled': bool(plugin.get('enabled'))})
    return found


def legacy_blocks():
    """Legacy managed blocks still present in the user's Hyprland files."""
    found = []
    input_text = trackpads.read_state_file(INPUT) or ''
    binds = trackpads.read_state_file(BINDINGS) or ''
    for path, text, (begin, end) in ((BINDINGS, binds, LEGACY_MIDDLE), (INPUT, input_text, LEGACY_DEVICE),
                                     (INPUT, input_text, LEGACY_GESTURES)):
        if begin in text and end in text:
            found.append({'file': str(path), 'marker': begin})
    if LEGACY_ANCHOR in input_text:
        found.append({'file': str(INPUT), 'marker': LEGACY_ANCHOR})
    return found


def status():
    plugins = other_plugins()
    blocks = legacy_blocks()
    return {
        'plugin': PLUGIN_ID,
        'others': plugins,
        'enabled_others': [p['id'] for p in plugins if p['enabled']],
        'legacy': blocks,
        'needs_attention': bool(plugins or blocks),
        # The touchpad settings file and the generated rules are shared with the
        # trackpad-plus plugin, so existing tuning is already in use here.
        'touchpad_settings_present': trackpads.read_state_file(trackpads.STATE) is not None,
        'remove_hint': [f'{REMOVE_HINT} {p["id"]}' for p in plugins],
    }


def backup(when=None):
    """Copy everything this plugin owns or edits into a private, timestamped folder."""
    stamp = when or time.strftime('%Y%m%d-%H%M%S')
    folder = BACKUPS / stamp
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(folder, 0o700)
    copied = []
    for path in owned_files():
        content = trackpads.read_state_file(path)
        if content is None:
            continue
        trackpads.atomic_write(folder / path.name, content)
        copied.append({'source': str(path), 'name': path.name, 'bytes': len(content)})
    manifest = {'created': stamp, 'plugin': PLUGIN_ID, 'files': copied}
    trackpads.atomic_write(folder / 'manifest.json', json.dumps(manifest, indent=2) + '\n')
    return {'folder': str(folder), 'files': copied}


def write_config(path, text, original):
    """Write a user's Hyprland file and put it back when Hyprland rejects it."""
    target = gestures.config_target(path) if path == INPUT else path
    trackpads.atomic_write(target, text)
    try:
        trackpads.reload_checked()
    except Exception:
        trackpads.atomic_write(target, original)
        trackpads.hypr('reload', 'config-only')
        raise


def legacy_sensitivity(block):
    match = re.search(r'(?<![\w.])sensitivity\s*=\s*(-?\d+(?:\.\d+)?)', block)
    return float(match.group(1)) if match else None


def device_block(text):
    begin, end = LEGACY_DEVICE
    start = text.find(begin)
    if start == -1:
        return None
    return text[start:text.find(end, start) + len(end)]


def adopt_middle_markers(text):
    """Rename the old binds block to this plugin's markers, dropping a duplicate."""
    begin, end = MIDDLE_MARKERS
    updated = text.replace(LEGACY_MIDDLE[0], begin).replace(LEGACY_MIDDLE[1], end)
    if updated.count(begin) > 1:
        # Keep the first block, remove any later one so binds are never doubled.
        first_end = updated.index(end, updated.index(begin)) + len(end)
        head, tail = updated[:first_end], updated[first_end:]
        pattern = re.compile(r'\n*' + re.escape(begin) + r'\n.*?' + re.escape(end) + r'\n?', re.S)
        updated = head + pattern.sub('\n', tail)
    return updated


def import_legacy():
    """Adopt the settings the replaced tools left behind. Backs up first."""
    result = backup()
    actions = []

    input_text = trackpads.read_state_file(INPUT)
    if input_text is not None:
        updated = input_text
        block = device_block(updated)
        if block is not None:
            keys = re.findall(r'(?<![\w.])(\w+)\s*=', block)
            value = legacy_sensitivity(block)
            if value is not None:
                device = trackpoint.detect_device()
                with trackpads.session() as (state, live, previous):
                    key = trackpads.device_key(state, device)
                    trackpads.change(state, key, 'sensitivity', value)
                actions.append(f'imported TrackPoint sensitivity {value}')
            if set(keys) - {'name', 'sensitivity'}:
                # The block carries options this plugin does not own: keep them and
                # drop only the setting that now comes from the generated rules.
                stripped = re.sub(r'\n?[ \t]*sensitivity\s*=\s*-?\d+(?:\.\d+)?[ \t]*,?', '', block)
                updated = updated.replace(block, stripped)
                actions.append('took over the TrackPoint sensitivity, leaving the other options')
            else:
                updated = updated.replace(block, '').rstrip('\n') + '\n'
                actions.append('removed the old TrackPoint device block')
        if LEGACY_GESTURES[0] in updated:
            updated = updated.replace(LEGACY_GESTURES[0], GESTURE_MARKERS[0]).replace(
                LEGACY_GESTURES[1], GESTURE_MARKERS[1])
            actions.append('renamed the gesture block to this plugin')
        if LEGACY_ANCHOR in updated:
            updated = updated.replace(LEGACY_ANCHOR, ANCHOR)
        if updated != input_text:
            write_config(INPUT, updated, input_text)

    binds = trackpads.read_state_file(BINDINGS)
    if binds is not None and LEGACY_MIDDLE[0] in binds:
        updated = adopt_middle_markers(binds)
        write_config(BINDINGS, updated, binds)
        actions.append('adopted the middle-button binds')

    result['actions'] = actions
    return result


def disable(plugin_id):
    """Back up, then disable another plugin. Never removes it."""
    if plugin_id == PLUGIN_ID:
        raise ValueError('Refusing to disable this plugin.')
    result = backup()
    subprocess.run(['omarchy', 'plugin', 'disable', plugin_id], capture_output=True, text=True, check=True)
    result['disabled'] = plugin_id
    result['uninstall_hint'] = f'{REMOVE_HINT} {plugin_id}'
    return result


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else 'status'
    if command == 'status' and len(sys.argv) == 2:
        print(json.dumps(status()))
    elif command == 'backup' and len(sys.argv) == 2:
        print(json.dumps(backup()))
    elif command == 'import' and len(sys.argv) == 2:
        print(json.dumps(import_legacy()))
    elif command == 'disable' and len(sys.argv) == 3:
        print(json.dumps(disable(sys.argv[2])))
    else:
        raise ValueError('Usage: adopt.py [status|backup|import|disable PLUGIN-ID]')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'error': str(exc)}))
        sys.exit(1)
