#!/usr/bin/env python3
"""Read and edit the TrackPoint middle button actions.

  middle.py                                 print status and every profile
  middle.py enable                          turn the middle button actions on
  middle.py disable                         turn them off and restore scrolling
  middle.py set <profile> <slot> <command>  set one action (empty clears it)
  middle.py add-app [window class]          add an app profile (default: focused app)
  middle.py remove-app <window class>       remove an app profile

Nothing in the Hyprland config changes until "enable". Enabling adds a marked
block of binds to bindings.lua and turns off the TrackPoint's hold-to-scroll,
so the button can tell a tap from a hold. Disabling removes the block and puts
the previous scroll setting back.

The "default" profile applies everywhere; an app profile overrides single
actions while that app is focused. bindings.lua only gets the binds some
profile uses, so unused modifier combos keep their normal behavior.
"""
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.dont_write_bytecode = True
import trackpads  # noqa: E402
import trackpoint  # noqa: E402

# Modifier taps, each its own Hyprland bind so they fire instantly
MODS = {
    'super': 'SUPER', 'alt': 'ALT', 'shift': 'SHIFT', 'ctrl': 'CTRL',
    'super_shift': 'SUPER + SHIFT', 'super_alt': 'SUPER + ALT', 'super_ctrl': 'SUPER + CTRL',
    'ctrl_alt': 'CTRL + ALT', 'ctrl_shift': 'CTRL + SHIFT', 'alt_shift': 'ALT + SHIFT',
}
SLOTS = ('tap', 'double', 'triple', 'hold', 'double_hold', 'triple_hold',
         'up', 'down', 'left', 'right') + tuple(MODS)
runner = Path(__file__).resolve().parent / 'middle_button.py'
state_dir = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state') / 'omarchy/trackpoint'
store = state_dir / 'middle.json'
config = Path.home() / '.config/hypr/bindings.lua'
begin = '-- BEGIN local.touchpad-tool middle button (managed by the Touchpad Tool bar widget)'
end = '-- END local.touchpad-tool middle button'
block = re.compile(r'\n?' + re.escape(begin) + r'\n.*?' + re.escape(end) + r'\n?', re.S)
usage = ('Usage: middle.py [enable | disable | set <profile> <slot> <command> | '
         'add-app [class] | remove-app <class>]')


def load():
    raw = trackpads.read_state_file(store)
    try:
        data = json.loads(raw) if raw is not None else {}
    except ValueError:
        data = {}
    profiles = {name: {slot: str(command) for slot, command in actions.items() if slot in SLOTS and command}
                for name, actions in (data.get('profiles') or {}).items() if isinstance(actions, dict)}
    profiles.setdefault('default', {})
    data['profiles'] = profiles
    data['enabled'] = bool(data.get('enabled'))
    return data


def save(state):
    # Middle-button settings live in the same hardened state path as device settings.
    trackpads.atomic_write(store, json.dumps(state, indent=2) + '\n')


def forget():
    try:
        with trackpads.state_directory(store.parent) as directory:
            os.unlink(store.name, dir_fd=directory)
            os.fsync(directory)
    except FileNotFoundError:
        pass


def bind_block(state):
    if not state['enabled']:
        return ''
    used = {slot for actions in state['profiles'].values() for slot in actions}
    run = f'python3 {shlex.quote(str(runner))}'
    lines = []
    if used - set(MODS):
        lines.append(f'o.bind("mouse:274", "TrackPoint middle button press", "{run} press")')
        lines.append(f'o.bind("mouse:274", "TrackPoint middle button release", "{run} release", {{ release = true }})')
    for slot, mods in MODS.items():
        if slot in used:
            label = ' + '.join(mod.title() for mod in mods.split(' + '))
            lines.append(f'o.bind("{mods} + mouse:274", "TrackPoint middle button {label} tap", "{run} mod {slot}")')
    return f'\n{begin}\n' + '\n'.join(lines) + f'\n{end}\n' if lines else ''


def reload():
    trackpads.reload_checked()


def write_binds(state):
    text = config.read_text()
    updated = block.sub('\n', text).rstrip('\n') + '\n' + bind_block(state)
    if updated == text:
        return
    config.write_text(updated)
    try:
        reload()
    except Exception:
        # Hyprland keeps running on a broken config, so put the file back.
        config.write_text(text)
        subprocess.run(['hyprctl', 'reload', 'config-only'], capture_output=True, text=True)
        raise


def focused_class():
    out = subprocess.run(['hyprctl', 'activewindow', '-j'], capture_output=True, text=True, check=True).stdout
    try:
        return json.loads(out).get('class', '')
    except (ValueError, AttributeError):
        return ''


def scroll_method(device):
    """The TrackPoint's saved scroll method, or None while it is left at the driver default."""
    with trackpads.session() as (state, live, previous):
        return state['devices'][trackpads.device_key(state, device)]['settings'].get('scroll_method')


def set_scroll_method(device, method):
    """Store and apply the scroll method through the shared device writer."""
    with trackpads.session() as (state, live, previous):
        trackpads.change(state, trackpads.device_key(state, device), 'scroll_method', method)


def enable(state):
    if state['enabled']:
        return
    device = trackpoint.detect_device()
    previous = scroll_method(device)
    # A programmable middle button needs the button back from hold-to-scroll.
    set_scroll_method(device, 'no_scroll')
    state.update(enabled=True, previous_scroll=previous)
    try:
        write_binds(state)
    except Exception:
        set_scroll_method(device, previous)
        raise


def disable(state):
    if not state['enabled']:
        return
    state['enabled'] = False
    write_binds(state)
    set_scroll_method(trackpoint.detect_device(), state.pop('previous_scroll', None))


try:
    state = load()
    previous_store = trackpads.read_state_file(store)
    result = {}
    args = sys.argv[1:]
    if args:
        profiles = state['profiles']
        if args == ['enable']:
            enable(state)
        elif args == ['disable']:
            disable(state)
        elif args[0] == 'set' and len(args) == 4:
            profile, slot, command = args[1], args[2], args[3].strip()
            if slot not in SLOTS:
                raise ValueError(f'Unknown action: {slot}')
            if profile not in profiles:
                raise ValueError(f'No profile for {profile}')
            if '\n' in command or '\r' in command:
                raise ValueError('Command must be a single line.')
            if command:
                profiles[profile][slot] = command
            else:
                profiles[profile].pop(slot, None)
        elif args[0] == 'add-app' and len(args) in (1, 2):
            app = (args[1] if len(args) == 2 else focused_class()).strip()
            if not app or app == 'default':
                raise ValueError('No focused app to add.')
            profiles.setdefault(app, {})
            result['added'] = app
        elif args[0] == 'remove-app' and len(args) == 2 and args[1] != 'default':
            profiles.pop(args[1], None)
        elif args != ['sync']:
            raise ValueError(usage)

        save(state)
        try:
            write_binds(state)
        except Exception:
            if previous_store is None:
                forget()
            else:
                trackpads.atomic_write(store, previous_store)
            raise

    result['enabled'] = state['enabled']
    result['profiles'] = state['profiles']
    print(json.dumps(result))
except Exception as exc:
    print(json.dumps({'error': str(exc)}))
    sys.exit(1)
