#!/usr/bin/env python3
"""Live fixture-only capture check. Does not modify configuration or save images."""
from pathlib import Path
import argparse
import json
import os
import re
import resource
import signal
import statistics
import subprocess
import time

ROOT = Path(__file__).resolve().parent


def command(*args):
    return subprocess.run(args, text=True, capture_output=True, timeout=4)


def hypr(query):
    result = command('hyprctl', '-j', query)
    result.check_returncode()
    return json.loads(result.stdout)


def address(value):
    if not re.fullmatch(r'0x[0-9a-f]+', value):
        raise ValueError('Invalid compositor window address')
    return value


def evaluate(code):
    result = command('hyprctl', 'eval', code)
    if result.returncode or result.stdout.strip() != 'ok':
        raise RuntimeError('Compositor operation failed: ' + result.stdout.strip())


def ipc(method, *args):
    result = command('qs', 'ipc', '-p', str(ROOT), 'call', '--', 'overviewProbe', method, *args)
    result.check_returncode()
    return result.stdout.strip()


def no_core_dump():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xwayland', action='store_true', help='Use real XWayland fixture windows')
    parser.add_argument('--cycles', type=int, default=0, help='Additional open/close cycles (0-100)')
    options = parser.parse_args()
    if not 0 <= options.cycles <= 100:
        parser.error('--cycles must be between 0 and 100')
    if command('omarchy-shell', 'lock', 'isLocked').stdout.strip() != 'false':
        raise RuntimeError('An unlocked Omarchy session is required')
    prior = hypr('activewindow')
    workspace = hypr('activeworkspace')
    other = next((w for w in hypr('workspaces') if w['id'] > 0
                  and w['id'] != workspace['id'] and w['monitor'] == workspace['monitor']), None)
    if not other:
        raise RuntimeError('An existing inactive workspace on the current monitor is required')
    processes = [None, None]
    try:
        environment = dict(os.environ)
        if options.xwayland:
            environment['QT_QPA_PLATFORM'] = 'xcb'
        processes[1] = subprocess.Popen(
            ['qs', '-p', str(ROOT / 'fixtures.qml'), '--no-color'], stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, preexec_fn=no_core_dump, env=environment)
        fixtures = []
        for _ in range(35):
            fixtures = [w for w in hypr('clients') if w['pid'] == processes[1].pid
                        and w['title'] in ['Trackpad Plus probe A', 'Trackpad Plus probe B']]
            if len(fixtures) == 2:
                break
            if processes[1].poll() is not None:
                raise RuntimeError('Probe process exited before becoming ready')
            time.sleep(0.1)
        if len(fixtures) != 2:
            raise RuntimeError('Fixture windows did not appear')
        assert all(bool(w['xwayland']) == options.xwayland for w in fixtures), 'Wrong fixture backend'
        target = next(w for w in fixtures if w['title'].endswith('B'))
        evaluate('hl.dispatch(hl.dsp.window.move({workspace="' + str(other['id'])
                 + '", window="address:' + address(target['address']) + '", follow=false}))')
        time.sleep(0.4)
        launch_started = time.monotonic()
        processes[0] = subprocess.Popen(
            ['qs', '-p', str(ROOT / 'shell.qml'), '--no-color'], stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, preexec_fn=no_core_dump)
        for _ in range(35):
            try:
                if ipc('status').startswith('{'):
                    break
            except subprocess.CalledProcessError:
                pass
            if processes[0].poll() is not None:
                raise RuntimeError('Probe process exited before becoming ready')
            time.sleep(0.05)
        else:
            raise RuntimeError('Probe IPC did not become ready')
        active = next(w for w in fixtures if w['title'].endswith('A'))
        for index, target in enumerate(fixtures + [active]):
            source = 'inactive' if target['title'].endswith('B') else 'active'
            if index == 2:
                evaluate('hl.dispatch(hl.dsp.window.fullscreen({window="address:'
                         + address(target['address']) + '", mode="fullscreen"}))')
                source = 'fullscreen'
                # Test an established fullscreen window, not its resize animation.
                previous_geometry = None
                stable = 0
                for _ in range(25):
                    current = next(w for w in hypr('clients') if w['address'] == target['address'])
                    geometry = (current['at'], current['size'], current['fullscreen'])
                    stable = stable + 1 if geometry == previous_geometry and current['fullscreen'] else 0
                    previous_geometry = geometry
                    if stable >= 5:
                        break
                    time.sleep(0.1)
                else:
                    raise RuntimeError('Fixture fullscreen geometry did not settle')
                # QtTest's synchronous readback can reuse the pre-resize
                # swapchain. Require normal presentation before inspecting it.
                # Two barriers also drain a frame queued before the first call.
                for barrier in range(2):
                    requested = command('qs', 'ipc', '-p', str(ROOT / 'fixtures.qml'), '--any-display',
                                        'call', '--', 'fixture', 'requestPresent')
                    requested.check_returncode()
                    for _ in range(30):
                        presented = command('qs', 'ipc', '-p', str(ROOT / 'fixtures.qml'), '--any-display',
                                            'call', '--', 'fixture', 'presentationCount')
                        presented.check_returncode()
                        if int(presented.stdout) > int(requested.stdout):
                            break
                        time.sleep(.05)
                    else:
                        raise RuntimeError('Fullscreen fixture did not present a fresh frame')
                for _ in range(20):
                    source_check = command('qs', 'ipc', '-p', str(ROOT / 'fixtures.qml'), '--any-display',
                                           'call', '--', 'fixture', 'checkSource')
                    source_check.check_returncode()
                    if source_check.stdout.strip() == 'true':
                        break
                    time.sleep(0.1)
                else:
                    diagnostic = command('qs', 'ipc', '-p', str(ROOT / 'fixtures.qml'), '--any-display',
                                         'call', '--', 'fixture', 'sourceStatus')
                    raise RuntimeError('Fullscreen source fixture pixels did not settle: ' + diagnostic.stdout.strip())
            before_focus = hypr('activewindow').get('address')
            assert ipc('open', address(target['address'])) == 'pending'
            for _ in range(35):
                state = json.loads(ipc('status'))
                if state['result'] not in ['checking-lock', 'capturing']:
                    break
                time.sleep(0.1)
            assert state['result'] == 'frame-ready', state
            if index == 0:
                print('Cold probe launch-to-frame:', round((time.monotonic() - launch_started) * 1000), 'ms'
                      ' (includes IPC readiness; no production gesture launcher yet)')
            assert state['hasContent'] and state['width'] > 0 and state['height'] > 0, state
            time.sleep(0.1)
            assert ipc('checkPixels') == 'true', json.loads(ipc('status'))['pixelCheck']
            assert hypr('activeworkspace')['id'] == workspace['id'], 'Capture changed workspace'
            print(source + ' workspace: actual pixels and orientation verified; '
                  + str(state['latencyMs']) + ' ms request-to-frame')
            result = command('wtype', '-k', 'Escape')
            result.check_returncode()
            time.sleep(0.15)
            closed = json.loads(ipc('status'))
            assert not closed['opened'] and not closed['hasContent'] and not closed['captureAttached'], closed
            assert closed['result'] == 'escape', closed
            assert hypr('activewindow').get('address') == before_focus, 'Escape did not restore application focus'
        if options.cycles:
            def resources():
                proc = Path('/proc') / str(processes[0].pid)
                rss = next(line.split()[1] for line in (proc / 'status').read_text().splitlines()
                           if line.startswith('VmRSS:'))
                return dict(rssKiB=int(rss), fileDescriptors=len(list((proc / 'fd').iterdir())))
            samples = []
            checkpoints = {'before': resources()}
            for cycle in range(options.cycles):
                ipc('open', address(active['address']))
                for _ in range(100):
                    state = json.loads(ipc('status'))
                    if state['result'] == 'frame-ready':
                        break
                    time.sleep(0.02)
                assert state['result'] == 'frame-ready', state
                samples.append(state['latencyMs'])
                ipc('close')
                state = json.loads(ipc('status'))
                assert not state['captureAttached'] and not state['hasContent'], state
                if cycle + 1 in [10, 30, 50, 100]:
                    checkpoints[str(cycle + 1)] = resources()
            ordered = sorted(samples[:30])
            print('Warm capture timing:', json.dumps(dict(samples=len(ordered),
                  medianMs=statistics.median(ordered), p95Ms=ordered[max(0, int(len(ordered)*0.95)-1)])))
            print('Resource checkpoints:', json.dumps(checkpoints))
        # A disappearing source must release the image and keep dismissal usable.
        ipc('open', address(active['address']))
        evaluate('hl.dispatch(hl.dsp.window.close({window="address:' + address(active['address']) + '"}))')
        time.sleep(0.3)
        closed_source = json.loads(ipc('status'))
        assert not closed_source['captureAttached'], closed_source
        ipc('close')
        # Terminating this process also releases its exclusive keyboard surface.
        remaining = next(w for w in fixtures if w['title'].endswith('B'))
        before_focus = hypr('activewindow').get('address')
        ipc('open', address(remaining['address']))
        time.sleep(0.3)
        children_file = Path('/proc') / str(processes[0].pid) / 'task' / str(processes[0].pid) / 'children'
        observers = [pid for pid in children_file.read_text().split()
                     if str(ROOT / 'lock-watch.py').encode() in (Path('/proc') / pid / 'cmdline').read_bytes()]
        assert len(observers) == 1, 'Expected one owned lock watcher'
        os.kill(int(observers[0]), signal.SIGTERM)
        for _ in range(30):
            state = json.loads(ipc('status'))
            if state['lockState'] == 'unknown' and not state['opened']:
                break
            time.sleep(0.05)
        assert state['lockState'] == 'unknown' and not state['opened'] and not state['captureAttached'] and not state['hasContent'], state
        print('Observer loss: failed closed; capture cleared without automatic reopen')
        ipc('open', address(remaining['address']))
        for _ in range(30):
            state = json.loads(ipc('status'))
            if state['result'] == 'frame-ready':
                break
            time.sleep(0.05)
        assert state['result'] == 'frame-ready', state
        child_pids = children_file.read_text().split()
        processes[0].kill()
        processes[0].wait(timeout=3)
        for _ in range(30):
            live_children = []
            for pid in child_pids:
                try:
                    status = (Path('/proc') / pid / 'status').read_text()
                except FileNotFoundError:
                    continue
                if not re.search(r'^State:\s+Z\b', status, re.MULTILINE):
                    live_children.append(pid)
            if not live_children:
                break
            time.sleep(0.05)
        assert not live_children, 'Lock watcher survived its consumer'
        assert hypr('activeworkspace')['id'] == workspace['id'], 'Termination changed workspace'
        assert hypr('activewindow').get('address') == before_focus, 'Termination did not restore focus'
        print('PASS: capture pixels, fullscreen/occlusion, Escape, source removal, SIGKILL/child cleanup and teardown.'
              ' Physical gestures and lock transitions remain separate gates.')
    finally:
        for process in processes:
            if process is None:
                continue
            if process.poll() is None:
                process.terminate()
        for process in processes:
            if process is None:
                continue
            try:
                output = process.communicate(timeout=3)[0]
            except subprocess.TimeoutExpired:
                process.kill()
                output = process.communicate()[0]
            errors = [line for line in output.splitlines() if 'ERROR' in line or 'qml:' in line]
            if errors:
                print('\n'.join(errors[-10:]))
        if (prior.get('address') and hypr('activeworkspace')['id'] == workspace['id']
                and command('omarchy-shell', 'lock', 'isLocked').stdout.strip() == 'false'):
            evaluate('hl.dispatch(hl.dsp.focus({window="address:' + address(prior['address']) + '"}))')


if __name__ == '__main__':
    main()
