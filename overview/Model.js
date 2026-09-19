// Pure navigation data: no capture, dispatch, logging, or compositor access.
//
// buildSnapshot accepts {session, monitorId, monitors, workspaces, windows,
// activeAddress, activeWorkspaceId}. Monitors have numeric id and string name,
// plus optional logical desktop coordinates {x,y,width,height};
// workspaces use Hyprland's {id,name,monitorID} (or monitor name), plus optional
// special. Windows use {address,pid,workspace:{id},monitor,hidden,mapped,title,
// class,token,at:[x,y],size:[width,height]}. The adapter MUST assign token once per live toplevel lifetime,
// never recycle it within a compositor session, and verify the same live source
// object before activation. PID/address alone cannot distinguish address reuse.
//
// Output: {session,monitorId,workspaces:[{key,id,name,active,windows:[{key,
// address,pid,token,workspaceId,title,appId,active,geometry}]}],selection}.
// geometry is {x,y,width,height} normalized to the monitor's logical extent and
// clipped to its bounds, or null for unavailable/invalid/offscreen geometry.
// The adapter resolves monitor scale/transform before supplying logical bounds.
// A selection is
// {kind:'window'|'workspace',key}, never a position. resolveSelection returns the
// current matching entry; reconcileSelection returns the valid selection or
// null. A disappeared selection does NOT fall back to another window. The
// initial selection uses activeAddress, then the active workspace, then null.
//
// Titles and workspace names are display text only. QML must use Qt.PlainText.
// Window moves retain their key within a session; moving outside the invocation
// monitor invalidates selection. Only workspaces already supplied are shown.

function integer(value) {
  return typeof value === "number" && isFinite(value)
    && Math.floor(value) === value && Math.abs(value) <= 9007199254740991
}

function identifier(value) {
  return typeof value === "string" && value.length > 0 && value.length <= 256
}

function address(value) {
  if (typeof value !== "string" || !/^(?:0x)?[0-9a-f]{1,16}$/i.test(value)) return ""
  var digits = value.toLowerCase().replace(/^0x/, "").replace(/^0+/, "")
  return digits ? "0x" + digits : ""
}

function text(value) {
  return typeof value === "string" ? value.slice(0, 4096) : ""
}

function compare(a, b) {
  return a < b ? -1 : a > b ? 1 : 0
}

function workspaceOnMonitor(workspace, monitor) {
  if (integer(workspace.monitorID)) return workspace.monitorID === monitor.id
  return (typeof monitor.name === "string" && monitor.name.length > 0
    && workspace.monitor === monitor.name) || workspace.monitor === monitor.id
}

function finiteNumber(value) {
  return typeof value === "number" && isFinite(value)
}

function desktopGeometry(window, monitor) {
  if (!Array.isArray(window.at) || window.at.length !== 2
      || !Array.isArray(window.size) || window.size.length !== 2
      || ![monitor.x, monitor.y, monitor.width, monitor.height,
        window.at[0], window.at[1], window.size[0], window.size[1]].every(finiteNumber)
      || monitor.width <= 0 || monitor.height <= 0
      || window.size[0] <= 0 || window.size[1] <= 0) return null
  var x = window.at[0] - monitor.x
  var y = window.at[1] - monitor.y
  var right = x + window.size[0]
  var bottom = y + window.size[1]
  if (![x, y, right, bottom].every(finiteNumber)) return null
  var left = Math.max(0, x) / monitor.width
  var top = Math.max(0, y) / monitor.height
  right = Math.min(monitor.width, right) / monitor.width
  bottom = Math.min(monitor.height, bottom) / monitor.height
  if (right <= left || bottom <= top) return null
  return { x: left, y: top, width: right - left, height: bottom - top }
}

function buildSnapshot(input) {
  input = input || {}
  var result = { session: identifier(input.session) ? input.session : "",
    monitorId: integer(input.monitorId) ? input.monitorId : null,
    workspaces: [], selection: null }
  if (!result.session || result.monitorId === null) return result
  var monitors = Array.isArray(input.monitors) ? input.monitors : []
  var matches = monitors.filter(function(m) { return m && m.id === result.monitorId })
  if (matches.length !== 1) return result
  var monitor = matches[0]
  var rawWorkspaces = Array.isArray(input.workspaces) ? input.workspaces : []
  var workspaceCounts = Object.create(null)
  rawWorkspaces.forEach(function(w) {
    if (w && integer(w.id)) workspaceCounts[w.id] = (workspaceCounts[w.id] || 0) + 1
  })
  var groups = Object.create(null)
  rawWorkspaces.forEach(function(w) {
    if (!w || !integer(w.id) || w.id === 0 || workspaceCounts[w.id] !== 1
        || w.special === true || w.name === "special"
        || (typeof w.name === "string" && w.name.indexOf("special:") === 0)
        || !workspaceOnMonitor(w, monitor)) return
    var group = { key: JSON.stringify([result.session, "workspace", w.id]),
      id: w.id, name: text(w.name) || String(w.id), active: w.id === input.activeWorkspaceId,
      windows: [] }
    groups[w.id] = group
    result.workspaces.push(group)
  })
  // Numeric workspaces first, then named workspaces by name and numeric ID.
  result.workspaces.sort(function(a, b) {
    if (a.id > 0 && b.id > 0) return compare(a.id, b.id)
    if ((a.id > 0) !== (b.id > 0)) return a.id > 0 ? -1 : 1
    return compare(a.name, b.name) || compare(a.id, b.id)
  })
  var windows = Array.isArray(input.windows) ? input.windows : []
  var addressCounts = Object.create(null)
  windows.forEach(function(w) {
    var normalized = w && address(w.address)
    if (normalized) addressCounts[normalized] = (addressCounts[normalized] || 0) + 1
  })
  var activeAddress = address(input.activeAddress)
  windows.forEach(function(w) {
    if (!w || !w.workspace || !integer(w.workspace.id)) return
    var group = groups[w.workspace.id]
    var normalized = address(w.address)
    if (!group || !normalized || addressCounts[normalized] !== 1
        || !identifier(w.token) || !integer(w.pid) || w.pid < 0
        || w.monitor !== result.monitorId || w.hidden === true || w.mapped === false) return
    var entry = { key: JSON.stringify([result.session, "window", normalized, w.pid, w.token]),
      address: normalized, pid: w.pid, token: w.token, workspaceId: group.id,
      title: text(w.title), appId: text(w.class), active: normalized === activeAddress,
      geometry: desktopGeometry(w, monitor) }
    group.windows.push(entry)
    if (entry.active) result.selection = { kind: "window", key: entry.key }
  })
  result.workspaces.forEach(function(w) {
    w.windows.sort(function(a, b) { return compare(a.key, b.key) })
    if (w.active && !result.selection) result.selection = { kind: "workspace", key: w.key }
  })
  return result
}

function resolveSelection(snapshot, selection) {
  if (!snapshot || !selection || !Array.isArray(snapshot.workspaces)) return null
  for (var i = 0; i < snapshot.workspaces.length; i++) {
    var workspace = snapshot.workspaces[i]
    if (selection.kind === "workspace" && selection.key === workspace.key) return workspace
    if (selection.kind !== "window") continue
    for (var j = 0; j < workspace.windows.length; j++) {
      if (selection.key === workspace.windows[j].key) return workspace.windows[j]
    }
  }
  return null
}

function reconcileSelection(snapshot, selection) {
  return resolveSelection(snapshot, selection)
    ? { kind: selection.kind, key: selection.key } : null
}

if (typeof module !== "undefined") {
  module.exports = { buildSnapshot: buildSnapshot, resolveSelection: resolveSelection,
    reconcileSelection: reconcileSelection }
}
