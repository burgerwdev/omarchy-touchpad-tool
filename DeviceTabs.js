// Which device tabs the panel shows, and what each tab is called.
// devices.py decides the tab keys and the default; this only maps that answer
// onto the tab row, so the names next to each tab always match the devices the
// backends will actually write to.
function model(deviceTabs, touchpads, trackpoints) {
  var names = { trackpad: touchpads || [], trackpoint: trackpoints || [] }
  var labels = { trackpad: "Trackpad", trackpoint: "TrackPoint" }
  var tabs = []
  for (var i = 0; i < (deviceTabs || []).length; i++) {
    var key = deviceTabs[i]
    if (!(key in names)) continue
    tabs.push({ key: key, label: labels[key], names: names[key] })
  }
  return tabs
}

// One device kind needs no tabs: the panel just shows that device's controls.
function showsRow(deviceTabs) { return (deviceTabs || []).length > 1 }

// Keep the visible tab across refreshes; follow the detected default when the
// current tab's device is gone.
function activeTab(current, deviceTabs, fallback) {
  if ((deviceTabs || []).indexOf(current) !== -1) return current
  return fallback || ""
}

if (typeof module !== "undefined") {
  module.exports = { model: model, showsRow: showsRow, activeTab: activeTab }
}
