#!/usr/bin/env python3
"""Run TrackPoint middle button actions from Hyprland's binds.

Hyprland calls this with "press" and "release", or "mod <name>" for a
modifier tap. Presses less than DOUBLE_TAP_SECONDS apart count together, up
to three. Holding past HOLD_SECONDS runs the hold action for that count, and
moving the pointer at least GESTURE_PIXELS while held makes the press a
flick gesture instead. A tap sequence runs as soon as no longer sequence has
an action, otherwise once the window closes. Actions come from the focused
app's profile, falling back to the default profile.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HOLD_SECONDS = 0.4
DOUBLE_TAP_SECONDS = 0.3
GESTURE_PIXELS = 40
TAPS = {1: 'tap', 2: 'double', 3: 'triple'}
HOLDS = {1: 'hold', 2: 'double_hold', 3: 'triple_hold'}
GESTURES = ('up', 'down', 'left', 'right')
state_dir = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state') / 'omarchy/trackpoint'
store = state_dir / 'middle.json'
# Press timing state is per-user; never fall back to the shared /tmp
runtime = Path(os.environ['XDG_RUNTIME_DIR']) if os.environ.get('XDG_RUNTIME_DIR') else state_dir
press_state = runtime / 'io.github.artmoreno.trackpoint-press.json'
tap_state = runtime / 'io.github.artmoreno.trackpoint-tap.json'


def hyprctl_json(*args):
    try:
        out = subprocess.run(['hyprctl', *args, '-j'], capture_output=True, text=True, timeout=1).stdout
        value = json.loads(out)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def profiles():
    try:
        data = json.loads(store.read_text())
    except Exception:
        data = {}
    return data.get('profiles') or {'default': {}}


def actions(all_profiles):
    merged = {k: v for k, v in all_profiles.get('default', {}).items() if isinstance(v, str) and v}
    if len(all_profiles) > 1:
        app = hyprctl_json('activewindow').get('class', '')
        merged.update({k: v for k, v in all_profiles.get(app, {}).items() if isinstance(v, str) and v})
    return merged


def cursor():
    pos = hyprctl_json('cursorpos')
    return [pos.get('x', 0), pos.get('y', 0)]


def direction(start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    if max(abs(dx), abs(dy)) < GESTURE_PIXELS:
        return ''
    if abs(dx) > abs(dy):
        return 'right' if dx > 0 else 'left'
    return 'down' if dy > 0 else 'up'


def run(command):
    # ":" is the explicit "do nothing" an app profile uses to block the default
    if command and command != ':':
        subprocess.Popen(command, shell=True, start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def read(path):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def main(args):
    action = args[0] if args else ''
    if action not in ('press', 'release', 'mod'):
        return
    all_profiles = profiles()
    # Grab the pointer before the slower focused-app lookup, or a quick flick
    # has already moved by the time the start position is read
    start = None
    if action == 'press' and any(p.get(g) for p in all_profiles.values() for g in GESTURES):
        start = cursor()
    cmds = actions(all_profiles)
    gestures = any(cmds.get(g) for g in GESTURES)

    if action == 'mod' and len(args) == 2:
        run(cmds.get(args[1], ''))

    elif action == 'press':
        # A tap still waiting for another makes this the next press in the sequence
        pending = read(tap_state)
        tap_state.unlink(missing_ok=True)
        count = min(pending.get('count', 0) + 1, 3)
        state = {'count': count, 'token': time.monotonic_ns()}
        if gestures:
            state['start'] = start
        write(press_state, state)
        hold = cmds.get(HOLDS[count], '')
        if hold:
            time.sleep(HOLD_SECONDS)
            # Release removes the press state, so a matching token means still held
            if read(press_state).get('token') == state['token']:
                # Moving while held is a gesture, which release handles
                if not (gestures and direction(state['start'], cursor())):
                    write(press_state, dict(state, fired=True))
                    run(hold)

    elif action == 'release':
        state = read(press_state)
        press_state.unlink(missing_ok=True)
        if not state or state.get('fired'):
            return
        count = state['count']
        flick = direction(state['start'], cursor()) if 'start' in state else ''
        if flick:
            run(cmds.get(flick, ''))
            return
        longest = max([n for n in TAPS if cmds.get(TAPS[n]) or cmds.get(HOLDS[n])], default=1)
        if count >= longest:
            run(cmds.get(TAPS[count], ''))
            return
        token = time.monotonic_ns()
        write(tap_state, {'count': count, 'token': token})
        time.sleep(DOUBLE_TAP_SECONDS)
        if read(tap_state).get('token') == token:
            tap_state.unlink(missing_ok=True)
            run(cmds.get(TAPS[count], ''))


if __name__ == '__main__':
    main(sys.argv[1:])
