// Device tab mapping: the panel shows exactly the tabs devices.py reported.
const assert = require('node:assert/strict');
const DeviceTabs = require('./DeviceTabs.js');

const TOUCHPAD = ['synaptics-tm3381-002'];
const TRACKPOINT = ['tpps/2-elan-trackpoint'];

function testBothDevicesShowBothNamedTabs() {
  const tabs = DeviceTabs.model(['trackpad', 'trackpoint'], TOUCHPAD, TRACKPOINT);
  assert.deepEqual(tabs.map(t => t.key), ['trackpad', 'trackpoint']);
  assert.deepEqual(tabs.map(t => t.label), ['Trackpad', 'TrackPoint']);
  assert.deepEqual(tabs[0].names, TOUCHPAD);
  assert.deepEqual(tabs[1].names, TRACKPOINT);
  assert.equal(DeviceTabs.showsRow(['trackpad', 'trackpoint']), true);
}

function testTouchpadOnlyHasNoTrackpointTab() {
  const tabs = DeviceTabs.model(['trackpad'], TOUCHPAD, []);
  assert.deepEqual(tabs.map(t => t.key), ['trackpad']);
  assert.equal(DeviceTabs.showsRow(['trackpad']), false);
}

function testTrackpointOnlyHasNoTrackpadTab() {
  const tabs = DeviceTabs.model(['trackpoint'], [], TRACKPOINT);
  assert.deepEqual(tabs.map(t => t.key), ['trackpoint']);
  assert.equal(DeviceTabs.showsRow(['trackpoint']), false);
}

function testNoDevicesMeansNoTabsAndNoRow() {
  assert.deepEqual(DeviceTabs.model([], [], []), []);
  assert.equal(DeviceTabs.showsRow([]), false);
}

function testUnknownTabKeyIsDropped() {
  assert.deepEqual(DeviceTabs.model(['trackpad', 'joystick'], TOUCHPAD, []).map(t => t.key), ['trackpad']);
}

function testActiveTabSurvivesRefreshAndFallsBackWhenGone() {
  assert.equal(DeviceTabs.activeTab('trackpoint', ['trackpad', 'trackpoint'], 'trackpad'), 'trackpoint');
  // The TrackPoint was unplugged: follow the detected default instead of a ghost tab.
  assert.equal(DeviceTabs.activeTab('trackpoint', ['trackpad'], 'trackpad'), 'trackpad');
  assert.equal(DeviceTabs.activeTab('trackpad', [], ''), '');
  assert.equal(DeviceTabs.activeTab('', ['trackpoint'], 'trackpoint'), 'trackpoint');
}

const tests = [
  testBothDevicesShowBothNamedTabs,
  testTouchpadOnlyHasNoTrackpointTab,
  testTrackpointOnlyHasNoTrackpadTab,
  testNoDevicesMeansNoTabsAndNoRow,
  testUnknownTabKeyIsDropped,
  testActiveTabSurvivesRefreshAndFallsBackWhenGone
];

for (const test of tests) {
  test();
  console.log('ok - ' + test.name);
}
console.log(tests.length + ' device tab tests passed');
