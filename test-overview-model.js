const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const Model = require('./overview/Model.js');

function window(address, workspaceId, extra = {}) {
  return { address, pid: 42, token: 'lifetime-' + address, workspace: { id: workspaceId },
    monitor: 0, mapped: true, hidden: false, title: 'Same title', class: 'app', ...extra };
}
function input(extra = {}) {
  return { session: 'session-a', monitorId: 0,
    monitors: [{ id: 0, name: 'internal' }, { id: 1, name: 'external' }],
    workspaces: [{ id: 2, name: '2', monitorID: 0 }, { id: 1, name: '1', monitor: 'internal' }],
    windows: [window('0x20', 2), window('0x10', 1)], activeAddress: '0x10', activeWorkspaceId: 1,
    ...extra };
}

// Ordering and selection do not follow the compositor's array positions.
{
  const raw = input();
  const untouched = JSON.stringify(raw);
  const model = Model.buildSnapshot(raw);
  assert.deepEqual(model.workspaces.map(w => w.id), [1, 2]);
  assert.equal(model.workspaces[0].active, true);
  assert.equal(Model.resolveSelection(model, model.selection).address, '0x10');
  const shuffled = Model.buildSnapshot({ ...raw, windows: raw.windows.slice().reverse(),
    workspaces: raw.workspaces.slice().reverse() });
  assert.deepEqual(shuffled, model);
  assert.equal(JSON.stringify(raw), untouched, 'normalization must not mutate live input');
}

// Named ordinary workspaces can have negative IDs. Empty known workspaces survive.
{
  const model = Model.buildSnapshot(input({ workspaces: [
    { id: -1337, name: 'Writing', monitorID: 0 }, { id: 7, name: '7', monitorID: 0 },
    { id: -1338, name: 'Art', monitorID: 0 }, { id: -99, name: 'special:scratch', monitorID: 0 },
    { id: 10, name: 'Hidden', monitorID: 0, special: true },
    { id: 9, name: '9', monitorID: 1 }
  ], windows: [window('0x10', -1337, { title: '<b>plain</b>\n$(command)', class: undefined }),
    window('0x20', -99), window('0x30', 10), window('0x40', 9, { monitor: 1 }),
    window('0x50', -1337, { hidden: true }), window('0x60', -1337, { mapped: false })],
    activeAddress: '', activeWorkspaceId: 7 }));
  assert.deepEqual(model.workspaces.map(w => w.id), [7, -1338, -1337]);
  assert.equal(model.workspaces[0].windows.length, 0);
  assert.equal(Model.resolveSelection(model, model.selection).id, 7);
  assert.equal(model.workspaces[2].windows.length, 1);
  assert.equal(model.workspaces[2].windows[0].title, '<b>plain</b>\n$(command)');
  assert.equal(model.workspaces[2].windows[0].appId, '');
}

// Stale selection cannot silently select another card, even with address/PID reuse.
{
  const before = Model.buildSnapshot(input());
  const selection = before.selection;
  const gone = Model.buildSnapshot(input({ windows: [window('0x20', 2)] }));
  assert.equal(Model.reconcileSelection(gone, selection), null);
  const reused = Model.buildSnapshot(input({ windows: [window('0x10', 1, { token: 'new-lifetime' })] }));
  assert.equal(Model.resolveSelection(reused, selection), null);
  const changedPid = Model.buildSnapshot(input({ windows: [window('0x10', 1, { pid: 43 })] }));
  assert.equal(Model.resolveSelection(changedPid, selection), null);
  const restarted = Model.buildSnapshot(input({ session: 'session-b' }));
  assert.equal(Model.resolveSelection(restarted, selection), null);
}

// A live lifetime follows a workspace move within this monitor, but never another monitor.
{
  const before = Model.buildSnapshot(input());
  const moved = Model.buildSnapshot(input({ windows: [window('0x10', 2)] }));
  assert.equal(Model.resolveSelection(moved, before.selection).workspaceId, 2);
  assert.deepEqual(Model.reconcileSelection(moved, before.selection), before.selection);
  const outside = Model.buildSnapshot(input({ windows: [window('0x10', 1, { monitor: 1 })] }));
  assert.equal(Model.resolveSelection(outside, before.selection), null);
  const workspaceMoved = Model.buildSnapshot(input({ workspaces: [{ id: 1, name: '1', monitorID: 1 }] }));
  assert.equal(Model.resolveSelection(workspaceMoved, before.selection), null);
  const unplugged = Model.buildSnapshot(input({ monitors: [{ id: 1, name: 'external' }] }));
  assert.deepEqual(unplugged.workspaces, []);
  assert.equal(unplugged.selection, null);
}

// Invalid and ambiguous records fail closed; no missing workspace is synthesized.
{
  const model = Model.buildSnapshot(input({ windows: [
    window('0x10;bad', 1), window('0x11', 1, { token: undefined }),
    window('0x12', 1, { pid: -1 }), window('0x13', 999),
    window('0x14', 1), window('0x14', 2, { token: 'duplicate' }),
    window('0X000F', 1), null
  ] }));
  assert.equal(model.workspaces[0].windows.length, 1);
  assert.equal(model.workspaces[0].windows[0].address, '0xf');
  assert.equal(model.workspaces[1].windows.length, 0);
  assert.equal(model.selection.kind, 'workspace');
  assert.deepEqual(Model.buildSnapshot(input({ workspaces: [
    { id: 1, monitorID: 0 }, { id: 1, monitorID: 0 }
  ] })).workspaces, []);
  assert.deepEqual(Model.buildSnapshot(null).workspaces, []);
  assert.deepEqual(Model.buildSnapshot(input({ monitors: [{ id: 0 }],
    workspaces: [{ id: 1, name: '1' }] })).workspaces, [],
    'missing monitor metadata must not match another missing field');
  assert.equal(Model.resolveSelection(model, { kind: 'window', key: 'wrong' }), null);
}

// Desktop placement uses logical monitor bounds, including negative origins.
// A geometry-only update must not change the window lifetime or selection key.
{
  const monitor = { id: 0, name: 'internal', x: -1600, y: -900, width: 1600, height: 900 };
  function snapshot(extra = {}, bounds = monitor) {
    return Model.buildSnapshot(input({ monitors: [bounds],
      windows: [window('0x10', 1, { at: [-1200, -675], size: [800, 450], ...extra })] }));
  }
  function geometry(extra = {}, bounds = monitor) {
    return snapshot(extra, bounds).workspaces[0].windows[0].geometry;
  }
  assert.deepEqual(geometry(), { x: 0.25, y: 0.25, width: 0.5, height: 0.5 });
  assert.deepEqual(geometry({ at: [-2000, -1125], size: [800, 450] }),
    { x: 0, y: 0, width: 0.25, height: 0.25 });
  assert.deepEqual(geometry({ at: [-400, -225], size: [800, 450] }),
    { x: 0.75, y: 0.75, width: 0.25, height: 0.25 });
  assert.deepEqual(geometry({ at: [-2000, -1125], size: [2400, 1350] }),
    { x: 0, y: 0, width: 1, height: 1 });
  // Adapter has already converted a scaled/rotated output into logical bounds.
  assert.deepEqual(geometry({ at: [1800, 550], size: [600, 800] },
    { id: 0, name: 'internal', x: 1500, y: 150, width: 1200, height: 1600 }),
  { x: 0.25, y: 0.25, width: 0.5, height: 0.5 });
  const before = snapshot();
  const moved = snapshot({ at: [-800, -450], size: [400, 225] });
  assert.deepEqual(moved.selection, before.selection);
  assert.equal(Model.resolveSelection(moved, before.selection).key,
    Model.resolveSelection(before, before.selection).key);

  for (const extra of [
    { at: [0, -900] }, { at: [-2400, -900] }, // Exactly outside right/left edge.
    { at: [-1600, 0] }, { at: [-1600, -1350] }, // Exactly outside bottom/top.
    { at: undefined }, { size: undefined }, { at: null }, { at: {} },
    { at: [-1600] }, { size: [100] }, { at: [-1600, -900, 0] },
    { size: [0, 100] }, { size: [100, -1] },
    { at: [NaN, 0] }, { size: [Infinity, 100] }, { at: ['0', 0] },
    { size: [true, 100] }, { at: [Symbol('invalid'), 0] }, { size: [1n, 100] },
    { at: [Number.MAX_VALUE, 0], size: [Number.MAX_VALUE, 100] }
  ]) assert.equal(geometry(extra), null, 'invalid/offscreen geometry uses the UI fallback');
  for (const bounds of [
    { x: undefined }, { y: NaN }, { width: 0 }, { height: -1 },
    { width: Infinity }, { height: '900' }, { x: -Number.MAX_VALUE }
  ]) {
    const extra = bounds.x === -Number.MAX_VALUE ? { at: [Number.MAX_VALUE, 0] } : {};
    assert.equal(geometry(extra, { ...monitor, ...bounds }), null);
  }
  const legacy = Model.buildSnapshot(input());
  assert.equal(legacy.workspaces[0].windows[0].geometry, null);
  assert.equal(geometry({}, { id: 0, name: 'internal' }), null);
}

// No CommonJS environment is needed by the QML-imported source.
{
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(path.join(__dirname, 'overview/Model.js'), 'utf8'), context);
  assert.equal(JSON.stringify(context.buildSnapshot(input())), JSON.stringify(Model.buildSnapshot(input())));
}
// Exercise the actual compositor event handler with controlled monitor identity.
// Real signal delivery on the invocation monitor is covered by the live harness.
{
  const shell = fs.readFileSync(path.join(__dirname, 'overview/shell.qml'), 'utf8');
  const handler = shell.match(/function onFocusedWorkspaceChanged\(\) \{([\s\S]*?)\n        \}/);
  assert.ok(handler, 'workspace event handler must exist');
  const invoke = new Function('root', 'Hyprland', 'session', handler[1]);
  function run(workspace, toplevel = null, opened = true) {
    const reasons = [];
    const root = {monitorId: 0, currentWorkspace: 1, currentActiveAddress: '0x10', rebuilds: 0,
      syncActiveToplevel() {
        if (!toplevel || !toplevel.monitor || !toplevel.workspace
            || toplevel.monitor.id !== this.monitorId || toplevel.workspace.id !== this.currentWorkspace) return false;
        const changed = this.currentActiveAddress !== toplevel.address;
        this.currentActiveAddress = toplevel.address;
        return changed;
      }, rebuild() { this.rebuilds++; }};
    const session = {opened, dismiss(reason) { reasons.push(reason); this.opened = false; }};
    invoke(root, {focusedWorkspace: workspace, activeToplevel: toplevel}, session);
    return {root, session, reasons};
  }
  const sameMonitor = run({id: 2, monitor: {id: 0}}, {address: '0x20', monitor: {id: 0}, workspace: {id: 2}});
  assert.equal(sameMonitor.root.currentWorkspace, 2);
  assert.equal(sameMonitor.root.currentActiveAddress, '0x20');
  assert.equal(sameMonitor.root.rebuilds, 1);
  assert.equal(sameMonitor.session.opened, true);
  assert.deepEqual(sameMonitor.reasons, []);
  for (const workspace of [{id: 3, monitor: {id: 1}}, {id: 3, monitor: null}, null]) {
    const result = run(workspace);
    assert.deepEqual(result.reasons, ['workspace-changed']);
    assert.equal(result.session.opened, false);
    assert.equal(result.root.currentWorkspace, 1);
    assert.equal(result.root.rebuilds, 0);
  }
  const hidden = run({id: 2, monitor: {id: 0}}, null, false);
  assert.deepEqual(hidden.reasons, []);
  assert.equal(hidden.root.rebuilds, 0);
  assert.equal(hidden.root.currentWorkspace, 1);
}
// An exclusive layer can clear activeToplevel; do not discard the last window.
{
  const shell = fs.readFileSync(path.join(__dirname, 'overview/shell.qml'), 'utf8');
  const handler = shell.match(/function syncActiveToplevel\(\) \{([\s\S]*?)\n    \}/);
  assert.ok(handler, 'active toplevel sync handler must exist');
  const invoke = new Function('root', 'Hyprland', 'with (root) { ' + handler[1] + ' }');
  function run(toplevel, current = '0x10', live = []) {
    const root = {monitorId: 0, currentWorkspace: 2, currentActiveAddress: current};
    return {changed: invoke(root, {activeToplevel: toplevel, toplevels: {values: live}}), address: root.currentActiveAddress};
  }
  assert.deepEqual(run(null), {changed: false, address: '0x10'});
  assert.deepEqual(run({address: '0x30', monitor: {id: 1}, workspace: {id: 2}}),
    {changed: false, address: '0x10'});
  assert.deepEqual(run({address: '0x20', monitor: {id: 0}, workspace: {id: 2}}),
    {changed: true, address: '0x20'});
  const focused = {address: '0x40', monitor: {id: 0}, workspace: {id: 2},
    lastIpcObject: {focusHistoryID: 0, mapped: true, hidden: false}};
  assert.deepEqual(run(null, '', [focused]), {changed: true, address: '0x40'});
  assert.deepEqual(run(null, '', [focused, {...focused, address: '0x41'}]),
    {changed: false, address: ''});
  assert.deepEqual(run(null, '', [{...focused, lastIpcObject: {focusHistoryID: 0, mapped: false, hidden: false}}]),
    {changed: false, address: ''});
}
// Selection rechecks session state after rebuild, which can dismiss the view.
{
  const shell = fs.readFileSync(path.join(__dirname, 'overview/shell.qml'), 'utf8');
  const handler = shell.match(/function select\(kind, key\) \{([\s\S]*?)\n    \}/);
  assert.ok(handler, 'selection handler must exist');
  const invoke = new Function('kind', 'key', 'session', 'rebuild', 'Model', 'snapshot', 'Hyprland', 'monitorId', 'activation', handler[1]);
  function run(opened, lockState, dismissDuringRebuild = false) {
    let dispatched = 0;
    const events = [];
    const session = {opened, lockState, dismiss(reason) { this.opened = false; events.push(reason); }};
    const model = Model.buildSnapshot(input());
    const workspace = model.workspaces[0];
    invoke('workspace', workspace.key, session, () => {
      if (dismissDuringRebuild) session.opened = false;
    }, Model, model, {workspaces: {values: [{id: workspace.id, monitor: {id: 0}, activate() {
      assert.equal(session.opened, false, 'Workspace click must release overview before dispatch');
      assert.deepEqual(events, ['selection']);
      dispatched++;
    }}]}}, 0, null);
    return dispatched;
  }
  assert.equal(run(true, 'unlocked'), 1);
  assert.equal(run(false, 'unlocked'), 0);
  assert.equal(run(true, 'locked'), 0);
  assert.equal(run(true, 'unknown'), 0);
  assert.equal(run(true, 'unlocked', true), 0);
}
console.log('Overview model, workspace event, and selection guard tests passed');

// Adapter normalizes physical monitor pixels before model clipping.
{
  const shell = fs.readFileSync(path.join(__dirname, 'overview/shell.qml'), 'utf8');
  const geometry = shell.match(/function monitorGeometry\(monitor\) \{([\s\S]*?)\n    \}/);
  const adapt = new Function('monitor', geometry[1]);
  const raw = {x: -1600, y: 0, width: 2560, height: 1600, scale: 1.6, transform: 0};
  assert.deepEqual(adapt({id: 0, name: 'test', lastIpcObject: raw}),
    {id: 0, name: 'test', x: -1600, y: 0, width: 1600, height: 1000});
  assert.equal(adapt({lastIpcObject: {...raw, transform: 1}}).width, 1000);
  assert.equal(adapt({lastIpcObject: {...raw, transform: 1}}).height, 1600);
  assert.ok(Number.isNaN(adapt({}).width));
}
// The + tile generates only an unused integer on the invocation monitor.
{
  const shell = fs.readFileSync(path.join(__dirname, 'overview/shell.qml'), 'utf8');
  const handler = shell.match(/function createWorkspace\(\) \{([\s\S]*?)\n    \}/);
  const invoke = new Function('session', 'Hyprland', 'monitorId', 'activation', handler[1]);
  function run(opened = true, lockState = 'unlocked', monitor = {id: 0}) {
    const calls = [];
    const session = {opened, lockState, dismiss(reason) {
      assert.equal(reason, 'selection'); this.opened = false;
    }};
    invoke(session, {focusedMonitor: monitor,
      workspaces: {values: [{id: 1}, {id: 2}, {id: 4}, {id: -99}]},
      dispatch(command) {
        assert.equal(session.opened, false, 'New workspace should be entered in one click');
        calls.push(command);
      }}, 0, null);
    return calls;
  }
  assert.deepEqual(run(), ['hl.dsp.focus({ workspace = "3" })']);
  assert.deepEqual(run(false), []);
  assert.deepEqual(run(true, 'locked'), []);
  assert.deepEqual(run(true, 'unknown'), []);
  assert.deepEqual(run(true, 'unlocked', null), []);
  assert.deepEqual(run(true, 'unlocked', {id: 1}), []);
}
console.log('Desktop geometry adapter and workspace creation tests passed');
