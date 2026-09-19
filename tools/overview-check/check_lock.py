#!/usr/bin/env python3
"""Interactive production overview lock test; unlock normally after five seconds."""
import os
import shutil
import signal
import tempfile
from pathlib import Path

from check import REPO, command, control, wait_for


def main():
    assert command('omarchy-shell', 'lock', 'isLocked') == 'false'
    command('wpctl', 'get-volume', '@DEFAULT_AUDIO_SINK@')
    with tempfile.TemporaryDirectory(prefix='trackpad-overview-lock-') as directory:
        base = Path(directory)
        shutil.copytree(REPO / 'overview', base / 'overview')
        shutil.copy2(REPO / 'manifest.json', base / 'manifest.json')
        companion = control.Controller(base)
        def state_matches(predicate):
            state = companion.execute('status')
            return state if predicate(state) else None
        try:
            state = companion.execute('open')
            pid = state['pid']
            wait_for(lambda: state_matches(lambda s: s.get('rendered')))
            print('Locking once. Please unlock normally after five seconds.', flush=True)
            command('omarchy', 'system', 'lock')
            state = wait_for(lambda: state_matches(lambda s: s.get('lockState') == 'locked'))
            assert not state['opened'] and not state['mapped'] and not state['rendered'] and state['captures'] == 0 and state['ready'] == 0
            state = companion.execute('open')
            assert not state['opened'] and not state['pending']
            children = Path('/proc', str(pid), 'task', str(pid), 'children')
            observers = [int(value) for value in children.read_text().split()
                if str(base / 'overview/lock-watch.py').encode() in Path('/proc', value, 'cmdline').read_bytes()]
            assert len(observers) == 1
            os.kill(observers[0], signal.SIGTERM)
            wait_for(lambda: state_matches(lambda s: s.get('lockState') == 'unknown'))
            state = companion.execute('open')
            assert state['lockState'] == 'locked' and not state['opened'] and not state['pending']
            print('PASS: capture destroyed on lock; locked and observer-restart opens rejected.', flush=True)
            state = wait_for(lambda: state_matches(lambda s: s.get('lockState') == 'unlocked'), seconds=120)
            assert not state['opened'] and not state['mapped'] and not state['rendered'] and state['captures'] == 0 and state['ready'] == 0
            command('wpctl', 'get-volume', '@DEFAULT_AUDIO_SINK@')
            command('pactl', 'get-sink-mute', '@DEFAULT_SINK@')
            print('PASS: unlock stays closed; audio controls responsive.', flush=True)
        finally:
            companion.execute('stop')


if __name__ == '__main__':
    main()
