#!/usr/bin/env python3
"""Capture real foot terminal windows; no images or application metadata saved."""
import json
import subprocess
import time

from check import ROOT, address, command, evaluate, hypr, ipc, no_core_dump


def main():
    assert command('omarchy-shell', 'lock', 'isLocked').stdout.strip() == 'false'
    prior = hypr('activewindow').get('address')
    workspace = hypr('activeworkspace')
    inactive = next(w for w in hypr('workspaces') if w['id'] > 0
                    and w['id'] != workspace['id'] and w['monitor'] == workspace['monitor'])
    processes = []
    # A real terminal renders text itself; the capture is never replaced by an
    # image painted into the overview. No user shell or shell history is loaded.
    text = '\n'.join(['Trackpad Plus application capture check'] * 25)
    try:
        for label in ('A', 'B'):
            processes.append(subprocess.Popen(
                ['foot', '--config=/dev/null', '--log-no-syslog', '--log-level=none',
                 '--title=Trackpad Plus probe ' + label, '--hold',
                 'python3', '-c', 'print(' + repr(text) + ')'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=no_core_dump))
        for _ in range(50):
            windows = [w for w in hypr('clients') if w['pid'] in [p.pid for p in processes]]
            if len(windows) == 2:
                break
            time.sleep(.1)
        assert len(windows) == 2, 'Application windows did not appear'
        active = next(w for w in windows if w['pid'] == processes[0].pid)
        other = next(w for w in windows if w['pid'] == processes[1].pid)
        evaluate('hl.dispatch(hl.dsp.window.move({workspace="' + str(inactive['id'])
                 + '",window="address:' + address(other['address']) + '",follow=false}))')
        processes.append(subprocess.Popen(['qs', '-n', '-p', str(ROOT / 'shell.qml')],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=no_core_dump))
        for _ in range(50):
            try:
                if json.loads(ipc('status'))['lockState'] == 'unlocked':
                    break
            except subprocess.CalledProcessError:
                pass
            time.sleep(.1)
        for label, target in [('active', active), ('inactive', other), ('fullscreen', active)]:
            if label == 'fullscreen':
                evaluate('hl.dispatch(hl.dsp.window.fullscreen({window="address:'
                         + address(target['address']) + '",mode="fullscreen"}))')
            time.sleep(.4)
            ipc('open', address(target['address']))
            for _ in range(30):
                state = json.loads(ipc('status'))
                if state['result'] == 'frame-ready':
                    break
                time.sleep(.1)
            assert state['result'] == 'frame-ready', state['result']
            time.sleep(.1)
            assert ipc('checkApplicationPixels') == 'true', 'Preview is blank or uniform'
            assert hypr('activeworkspace')['id'] == workspace['id'], 'Capture switched workspaces'
            print(label + ': real application preview has contrasting pixels; workspace preserved')
            ipc('close')
            state = json.loads(ipc('status'))
            assert not state['hasContent'] and not state['captureAttached'] and not state['opened']
        print('PASS: real foot application capture and teardown')
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if (prior and hypr('activeworkspace')['id'] == workspace['id']
                and command('omarchy-shell', 'lock', 'isLocked').stdout.strip() == 'false'):
            evaluate('hl.dispatch(hl.dsp.focus({window="address:' + address(prior) + '"}))')


if __name__ == '__main__':
    main()
