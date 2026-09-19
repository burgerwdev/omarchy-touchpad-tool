#!/usr/bin/env python3
"""Live overview integration check using owned terminals; never saves images.

Requires an unlocked session. Creates an inactive workspace for an owned fixture,
temporarily opens the overview, then removes its fixtures and restores focus.
"""
import argparse
import importlib.util
import json
import os
import signal
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
spec = importlib.util.spec_from_file_location('overview_control', REPO / 'overview-control.py')
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


def command(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=5)
    result.check_returncode()
    return result.stdout.strip()


def hypr(name):
    return json.loads(command('hyprctl', '-j', name))


def evaluate(code):
    assert command('hyprctl', 'eval', code) == 'ok'


def wait_for(check, seconds=4):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(.025)
    raise AssertionError('Live overview check timed out')


# Inject observability only into a temporary copy, never the installed shell.
# Pixels are sampled in memory and restricted to our constant-title fixtures.
INSTRUMENT = r'''
    property int testBadWallpaperFrames: 0
    TestResult { id: pixels }
    function testCards() {
        const view = root.testOverview();
        return view ? view.cards.filter(card => card && card.captureState !== undefined && card.captureState !== "retired") : [];
    }
    function testOverview() {
        let found = null;
        function walk(item) {
            if (!item || found) return;
            if (item.cards !== undefined && item.snapshot !== undefined) { found = item; return; }
            for (let child of item.children || []) walk(child);
        }
        if (overlay.item) walk(overlay.item.contentItem);
        return found;
    }
    IpcHandler {
        target: "overviewCheck"
        function fixture(address: string): string {
            const card = root.testCards().find(c => c.entry.address === address && !c.compact);
            if (!card) return "not-visible";
            return card.captureState;
        }
        function pixelsOk(address: string, thumbnail: bool): bool {
            const card = root.testCards().find(c => c.entry.address === address && c.compact === thumbnail);
            if (!card || card.captureState !== "ready") return false;
            const image = pixels.grabImage(card);
            let low = 255, high = 0;
            // Exclude borders, footer title and controls from the contrast check.
            const step = thumbnail ? 1 : Math.max(1, Math.floor(image.width / 100));
            for (let y = Math.ceil(image.height * .1); y < image.height * .8; y += step)
                for (let x = Math.ceil(image.width * .1); x < image.width * .9; x += step) {
                const value = (image.red(x,y) + image.green(x,y) + image.blue(x,y)) / 3;
                low = Math.min(low,value); high = Math.max(high,value);
            }
            return high - low > 80;
        }
        function revealThumbnail(address: string): bool {
            const overview = root.testOverview();
            if (!overview) return false;
            const index = root.snapshot.workspaces.findIndex(workspace => {
                const representative = workspace.windows.find(w => w.active) || workspace.windows[0];
                return representative && representative.address === address;
            });
            if (index < 0) return false;
            let strip = null;
            function walk(item) {
                if (!item || strip) return;
                if (item.objectName === "workspaceStrip") { strip = item; return; }
                for (let child of item.children || []) walk(child);
            }
            walk(overview);
            if (!strip) return false;
            strip.positionViewAtIndex(index, ListView.Contain);
            return true;
        }
        function selectFixture(address: string): bool {
            const entry = root.snapshot.workspaces.reduce((all, w) => all.concat(w.windows), []).find(w => w.address === address);
            if (!entry) return false;
            root.select("window", entry.key);
            return true;
        }
        function selectWorkspace(id: int): bool {
            const workspace = root.snapshot.workspaces.find(w => w.id === id);
            if (!workspace) return false;
            root.select("workspace", workspace.key);
            return true;
        }
        function cardAndPage(address: string): string {
            const card = root.testCards().find(c => c.entry.address === address && !c.compact);
            const overview = root.testOverview();
            if (!card || !overview) return "unavailable";
            return JSON.stringify({card: String(card), capture: card.captureState,
                workspace: overview.activeWorkspace.id, page: overview.windowPage});
        }
        function rebuildNoop(address: string): string {
            root.rebuild();
            return cardAndPage(address);
        }
        function currentWorkspace(): int {
            const overview = root.testOverview();
            return overview && overview.activeWorkspace ? overview.activeWorkspace.id : 0;
        }
        function addWorkspace(): bool {
            let button = null;
            function walk(item) {
                if (!item || button) return;
                if (item.objectName === "newWorkspace") { button = item; return; }
                for (let child of item.children || []) walk(child);
            }
            walk(root.testOverview());
            if (!button) return false;
            button.clicked();
            return true;
        }
        function backdropReady(): bool {
            let ready = false;
            function walk(item) {
                if (!item) return;
                if (item.objectName === "preparedWallpaper") ready = item.ready;
                for (let child of item.children || []) walk(child);
            }
            if (overlay.item) walk(overlay.item.contentItem);
            return ready;
        }
        function badWallpaperFrames(): int { return root.testBadWallpaperFrames; }
    }
}
'''


def usage(pid):
    data = Path('/proc', str(pid), 'status').read_text()
    rss = next(int(line.split()[1]) for line in data.splitlines() if line.startswith('VmRSS:'))
    return dict(rssKiB=rss, fds=len(list(Path('/proc', str(pid), 'fd').iterdir())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycles', type=int, default=0)
    args = parser.parse_args()
    if not 0 <= args.cycles <= 100:
        parser.error('cycles must be 0–100')
    assert command('omarchy-shell', 'lock', 'isLocked') == 'false'
    prior = hypr('activewindow').get('address')
    original = hypr('activeworkspace')
    # A new workspace makes our second fixture the real representative without
    # rearranging any user windows or substituting a test-only snapshot.
    other_id = max([w['id'] for w in hypr('workspaces')] + [0]) + 1
    owned = []
    with tempfile.TemporaryDirectory(prefix='trackpad-overview-live-') as directory:
        base = Path(directory)
        shutil.copytree(REPO / 'overview', base / 'overview')
        shutil.copy2(REPO / 'manifest.json', base / 'manifest.json')
        shell = base / 'overview/shell.qml'
        source = shell.read_text().replace('import QtQuick\n', 'import QtQuick\nimport QtTest\n', 1)
        source = source.replace('    LazyLoader {', '    LazyLoader {\n        id: overlay')
        frame_handler = 'if (panel.visible) { session.mapped'
        assert frame_handler in source
        source = source.replace(frame_handler,
            'if (panel.visible && !preparedWallpaper.preparedForOpen) root.testBadWallpaperFrames++;\n                    ' + frame_handler)
        shell.write_text(source.rstrip()[:-1] + INSTRUMENT)
        companion = control.Controller(base)
        try:
            title_files = []
            for index in range(2):
                title_file = base / ('fixture-title-' + str(index))
                title_file.write_text('Trackpad Plus overview check')
                title_files.append(title_file)
                fixture_program = (
                    'from pathlib import Path\nimport time\n'
                    + 'path = Path(' + repr(str(title_file)) + ')\n'
                    + 'print("Trackpad Plus live preview check\\n" * 30, flush=True)\n'
                    + 'previous = None\nwhile True:\n'
                    + '    title = path.read_text().strip()\n'
                    + '    if title != previous:\n'
                    + '        print("\\x1b]2;" + title + "\\x07", flush=True)\n'
                    + '        previous = title\n'
                    + '    time.sleep(.05)\n')
                owned.append(subprocess.Popen(['foot', '--config=/dev/null', '--log-no-syslog', '--log-level=none',
                    '--title=Trackpad Plus overview check', '--hold', 'python3', '-c', fixture_program],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0, 0))))
            fixtures = wait_for(lambda: (windows if len(windows := [w for w in hypr('clients') if w['pid'] in [p.pid for p in owned]]) == 2 else None))
            first, second = [next(w for w in fixtures if w['pid'] == process.pid) for process in owned]
            assert not any(w['id'] == other_id for w in hypr('workspaces')), 'Temporary workspace was created concurrently'
            evaluate('hl.dispatch(hl.dsp.window.move({workspace="%d",window="address:%s",follow=false}))' % (other_id, second['address']))
            other = wait_for(lambda: next((w for w in hypr('workspaces') if w['id'] == other_id), None))
            assert other['monitor'] == original['monitor'], 'Temporary fixture workspace is on a different monitor'
            evaluate('hl.dispatch(hl.dsp.focus({window="address:%s"}))' % first['address'])
            time.sleep(.25)
            begin = time.monotonic()
            reply = companion.execute('open')
            pid = reply['pid']
            wait_for(lambda: companion.execute('status')['rendered'])
            cold = round((time.monotonic() - begin) * 1000)
            ipc = lambda method, *values: command('qs', 'ipc', '--pid', str(pid), 'call', 'overviewCheck', method, *map(str, values))
            wait_for(lambda: ipc('backdropReady') == 'true')
            wait_for(lambda: ipc('fixture', first['address']) == 'ready')
            wait_for(lambda: ipc('pixelsOk', first['address'], 'false') == 'true')
            assert hypr('activeworkspace')['id'] == original['id'], 'Capturing changed the active workspace'
            wait_for(lambda: ipc('pixelsOk', first['address'], 'true') == 'true')
            focused_before = hypr('activewindow').get('address')
            assert ipc('revealThumbnail', second['address']) == 'true', 'Inactive fixture is not the workspace representative'
            wait_for(lambda: ipc('pixelsOk', second['address'], 'true') == 'true')
            assert hypr('activeworkspace')['id'] == original['id'], 'Inactive thumbnail capture activated its workspace'
            assert ipc('currentWorkspace') == str(original['id']), 'Inactive thumbnail changed the overview workspace'
            assert hypr('activewindow').get('address') == focused_before, 'Inactive thumbnail capture changed window focus'
            assert ipc('revealThumbnail', first['address']) == 'true'
            print('PASS: current and inactive workspace thumbnails contain fixture pixels without changing workspace or focus')
            before_title = json.loads(ipc('cardAndPage', first['address']))
            assert json.loads(ipc('rebuildNoop', first['address'])) == before_title, 'No-op rebuild replaced ready card'
            title_files[0].write_text('Trackpad Plus overview title update')
            wait_for(lambda: next(window for window in hypr('clients') if window['pid'] == owned[0].pid)['title'] == 'Trackpad Plus overview title update')
            time.sleep(.25)
            assert json.loads(ipc('cardAndPage', first['address'])) == before_title, 'Title-only update replaced ready card'
            print('PASS: title and no-op updates preserve ready capture')
            companion.execute('close')
            evaluate('hl.dispatch(hl.dsp.window.fullscreen({window="address:%s",mode="fullscreen"}))' % first['address'])
            time.sleep(.4)
            companion.execute('open')
            wait_for(lambda: ipc('fixture', first['address']) == 'ready')
            # Capture completion can precede the QML frame that paints it.
            # Require actual fixture pixels within the same bounded deadline.
            wait_for(lambda: ipc('pixelsOk', first['address'], 'false') == 'true')
            companion.execute('close')
            evaluate('hl.dispatch(hl.dsp.window.fullscreen({window="address:%s",mode="fullscreen"}))' % first['address'])
            companion.execute('close')
            wait_for(lambda: hypr('activewindow').get('address') == first['address'])
            assert not companion.execute('status')['mapped']
            companion.execute('open')
            wait_for(lambda: companion.execute('status')['rendered'])
            assert ipc('selectWorkspace', other['id']) == 'true'
            wait_for(lambda: hypr('activeworkspace')['id'] == other['id'])
            assert not companion.execute('status')['opened'], 'Workspace click did not dismiss overview'
            companion.execute('open')
            wait_for(lambda: ipc('fixture', second['address']) == 'ready')
            wait_for(lambda: ipc('pixelsOk', second['address'], 'false') == 'true')
            assert ipc('selectFixture', second['address']) == 'true'
            wait_for(lambda: hypr('activewindow').get('address') == second['address'])
            assert hypr('activeworkspace')['id'] == other['id']
            companion.execute('open')
            wait_for(lambda: companion.execute('status')['mapped'])
            assert ipc('selectWorkspace', original['id']) == 'true'
            wait_for(lambda: hypr('activeworkspace')['id'] == original['id'])
            companion.execute('open')
            wait_for(lambda: companion.execute('status')['mapped'])
            evaluate('hl.dispatch(hl.dsp.focus({workspace="%d"}))' % other['id'])
            wait_for(lambda: ipc('currentWorkspace') == str(other['id']))
            assert companion.execute('status')['opened'], 'External workspace switch closed overview'
            assert hypr('activeworkspace')['id'] == other['id']
            evaluate('hl.dispatch(hl.dsp.focus({workspace="%d"}))' % original['id'])
            wait_for(lambda: ipc('currentWorkspace') == str(original['id']))
            existing_ids = {w['id'] for w in hypr('workspaces')}
            assert ipc('addWorkspace') == 'true', 'Add-workspace tile is unavailable'
            created = wait_for(lambda: (w if (w := hypr('activeworkspace'))['id'] not in existing_ids else None))
            assert not companion.execute('status')['opened'], 'New workspace click did not dismiss overview'
            assert created['monitor'] == original['monitor']
            evaluate('hl.dispatch(hl.dsp.focus({workspace="%d"}))' % original['id'])
            companion.execute('close')
            print('PASS: wallpaper loaded; workspace and + tiles enter the desktop in one click')
            assert ipc('backdropReady') == 'true', 'Closing discarded the prepared wallpaper'
            assert ipc('badWallpaperFrames') == '0', 'A visible frame used an unprepared wallpaper'
            print('PASS: wallpaper ready on every visible frame and retained while hidden')
            print('PASS: current/inactive workspace pixels, exact window selection, workspace selection, close/focus, external workspace change')
            before = usage(pid)
            peak = dict(before)
            latencies = []
            for _ in range(args.cycles):
                begin = time.monotonic()
                companion.execute('open')
                state = wait_for(lambda: (s if (s := companion.execute('status'))['rendered'] else None))
                assert state['captures'] <= 2
                latencies.append((time.monotonic() - begin) * 1000)
                current = usage(pid)
                peak = {key: max(peak[key], current[key]) for key in peak}
                companion.execute('close')
                state = companion.execute('status')
                assert not state['mapped'] and not state['rendered'] and state['captures'] == 0
                assert ipc('backdropReady') == 'true'
                assert ipc('badWallpaperFrames') == '0'
                time.sleep(.06)
            if latencies:
                print(json.dumps(dict(cycles=args.cycles, coldMs=cold, warmMedianMs=round(statistics.median(latencies[:30])),
                    warmP95Ms=round(sorted(latencies[:30])[int(len(latencies[:30]) * .95) - 1]),
                    before=before, peak=peak, settled=usage(pid))))
            else:
                print(json.dumps(dict(coldMs=cold, usage=usage(pid))))
            # Kill only our verified companion; its observer must exit with it.
            children = Path('/proc', str(pid), 'task', str(pid), 'children')
            observer_pids = [int(value) for value in children.read_text().split()
                if str(base / 'overview/lock-watch.py').encode() in Path('/proc', value, 'cmdline').read_bytes()]
            os.kill(pid, signal.SIGKILL)
            wait_for(lambda: not companion.execute('status')['reachable'])
            wait_for(lambda: all(not Path('/proc', str(child)).exists()
                or Path('/proc', str(child), 'stat').read_text().split(') ')[1].startswith('Z ')
                for child in observer_pids))
            assert not companion.execute('start')['opened']
            assert not command('hyprctl', 'configerrors')
            print('PASS: forced companion exit releases observer; explicit restart stays hidden')

        finally:
            try:
                companion.execute('stop')
            finally:
                for process in owned:
                    if process.poll() is None:
                        process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait()
                if command('omarchy-shell', 'lock', 'isLocked') == 'false':
                    evaluate('hl.dispatch(hl.dsp.focus({workspace="%d"}))' % original['id'])
                    if prior and any(w['address'] == prior for w in hypr('clients')):
                        evaluate('hl.dispatch(hl.dsp.focus({window="address:%s"}))' % prior)



if __name__ == '__main__':
    main()
