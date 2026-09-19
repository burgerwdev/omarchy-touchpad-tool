#!/usr/bin/env python3
"""Interactive real-session lock check. Locks the desktop; user must unlock it."""
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from check import ROOT, address, command, evaluate, hypr, ipc, no_core_dump


def wait_for(predicate, seconds=4):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        state = json.loads(ipc('status'))
        if predicate(state):
            return state
        time.sleep(.05)
    raise RuntimeError('Expected lock/capture state was not observed')


def main():
    assert command('omarchy-shell', 'lock', 'isLocked').stdout.strip() == 'false'
    # Refuse a new lock test if the prior audio failure is still present.
    command('wpctl', 'get-volume', '@DEFAULT_AUDIO_SINK@').check_returncode()
    prior = hypr('activewindow').get('address')
    workspace = hypr('activeworkspace')['id']
    processes = []
    try:
        for name in ('fixtures.qml', 'shell.qml'):
            processes.append(subprocess.Popen(['qs', '-n', '-p', str(ROOT / name)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=no_core_dump))
        target = None
        for _ in range(40):
            target = next((w['address'] for w in hypr('clients') if w['pid'] == processes[0].pid
                           and w['title'] == 'Trackpad Plus probe A'), None)
            try:
                state = json.loads(ipc('status'))
                if target and state['lockState'] == 'unlocked':
                    break
            except subprocess.CalledProcessError:
                pass
            time.sleep(.1)
        assert target, 'Owned fixture did not appear'
        ipc('open', address(target))
        wait_for(lambda s: s['result'] == 'frame-ready')
        print('Locking the desktop. Please unlock normally after five seconds.', flush=True)
        command('omarchy', 'system', 'lock').check_returncode()
        state = wait_for(lambda s: s['lockState'] == 'locked')
        assert not state['opened'] and not state['hasContent'] and not state['captureAttached']
        print('PASS: real lock cleared visible capture', flush=True)
        ipc('open', address(target))
        state = wait_for(lambda s: s['result'] == 'lock-locked')
        assert not state['opened'] and not state['hasContent'] and not state['pending']
        print('PASS: open while locked was rejected', flush=True)
        # Lose and re-establish observation while the real compositor is locked.
        # The open request is pending during the new observer's initial sync.
        children = Path('/proc') / str(processes[1].pid) / 'task' / str(processes[1].pid) / 'children'
        observers = [pid for pid in children.read_text().split()
                     if str(ROOT / 'lock-watch.py').encode() in (Path('/proc') / pid / 'cmdline').read_bytes()]
        assert len(observers) == 1
        os.kill(int(observers[0]), signal.SIGTERM)
        wait_for(lambda s: s['lockState'] == 'unknown' and s['result'] == 'lock-unavailable')
        ipc('open', address(target))
        state = wait_for(lambda s: s['lockState'] == 'locked' and not s['pending'])
        assert not state['opened'] and not state['hasContent'] and not state['captureAttached']
        print('PASS: pending open after observer restart remained closed in the locked session', flush=True)
        state = wait_for(lambda s: s['lockState'] == 'unlocked', seconds=120)
        assert not state['opened'] and not state['hasContent'] and not state['captureAttached']
        print('PASS: unlock did not reopen or retain a preview', flush=True)
        command('wpctl', 'get-volume', '@DEFAULT_AUDIO_SINK@').check_returncode()
        command('pactl', 'get-sink-mute', '@DEFAULT_SINK@').check_returncode()
        print('PASS: audio controls responsive after lock/unlock', flush=True)
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if (prior and hypr('activeworkspace')['id'] == workspace
                and command('omarchy-shell', 'lock', 'isLocked').stdout.strip() == 'false'):
            evaluate('hl.dispatch(hl.dsp.focus({window="address:' + address(prior) + '"}))')


if __name__ == '__main__':
    main()
