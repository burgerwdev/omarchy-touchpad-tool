pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as Controls
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons
import "DeviceTabs.js" as DeviceTabs

// One bar widget for both pointing devices. The top-level Trackpad/TrackPoint
// tabs are chosen by what the machine actually has attached; each tab keeps the
// layout and controls of the tool it came from.
Panel {
  id: root
  moduleName: "local.touchpad-tool"
  ipcTarget: "local.touchpad-tool"
  manageIpc: true

  property string releaseVersion: ""
  FileView {
    path: Qt.resolvedUrl("manifest.json")
    onLoaded: {
      try { root.releaseVersion = JSON.parse(text()).version || "" }
      catch (error) { root.releaseVersion = "" }
    }
  }

  // ---- Bar icon ----
  readonly property string logo: ["wordmark", "dot", "color"].indexOf(String(setting("logo", "wordmark"))) !== -1
    ? String(setting("logo", "wordmark")) : "wordmark"
  readonly property var logoOptions: [
    { value: "wordmark", label: "ThinkPad" },
    { value: "dot", label: "Red dot" },
    { value: "color", label: "Color logo" }
  ]
  function setLogo(value) {
    if (logoWriter.running || value === logo) return
    // Omarchy's own command stores it on this widget's bar entry, so the icon updates live.
    logoWriter.command = ["omarchy", "bar", "set", "local.touchpad-tool", "logo", value]
    logoWriter.running = true
  }

  // ---- Detected hardware ----
  // devices.py owns the classification and the tab list, so the panel, the
  // touchpad backend and the TrackPoint backend can never disagree.
  property var touchpads: []
  property var trackpoints: []
  property var deviceTabs: []
  readonly property bool hasTouchpad: touchpads.length > 0
  readonly property bool hasTrackPoint: trackpoints.length > 0
  readonly property bool bothDevices: DeviceTabs.showsRow(deviceTabs)
  readonly property var deviceTabModel: DeviceTabs.model(deviceTabs, touchpads, trackpoints)
  property string activeDeviceTab: ""
  property string deviceStatus: ""

  function detectDevices() {
    if (!detectProc.running) detectProc.running = true
  }

  function receiveDevices(raw) {
    var data
    try { data = JSON.parse(raw) } catch (error) { deviceStatus = "Could not read input devices."; return }
    if (data.error) { deviceStatus = data.error; return }
    touchpads = data.touchpads || []
    trackpoints = data.trackpoints || []
    deviceTabs = data.tabs || []
    deviceStatus = ""
    // A device can be unplugged between refreshes: fall back to whatever is left.
    activeDeviceTab = DeviceTabs.activeTab(activeDeviceTab, deviceTabs, data.default_tab)
  }

  function changeDeviceTab(tab) {
    if (root.activeDeviceTab === tab) return
    activeDeviceTab = tab
  }

  // The loaded tab body owns its own keyboard navigation; the merged panel only
  // routes keys into whichever body is showing.
  readonly property var activeBody: deviceBody.item || null
  readonly property real bodyWidth: root.activeBody && root.activeBody.contentWidth
    ? root.activeBody.contentWidth : Style.space(360)
  function bodyFunction(name) {
    return root.activeBody && typeof root.activeBody[name] === "function" ? root.activeBody[name] : null
  }

  // ---- Other tools that manage these devices ----
  // Nothing here disables or removes anything by itself: every action is a press
  // in the panel, and each one backs up first.
  property var adoptOthers: []
  property var adoptLegacy: []
  property string adoptStatus: ""
  property string adoptRemoveHint: ""
  readonly property bool adoptEnabledOthers: adoptOthers.some(function(plugin) { return plugin.enabled })
  readonly property bool adoptNeedsAttention: adoptOthers.length > 0 || adoptLegacy.length > 0
  readonly property string adoptSummary: {
    var parts = []
    for (var i = 0; i < adoptOthers.length; i++)
      parts.push(adoptOthers[i].name + (adoptOthers[i].enabled ? " (enabled)" : " (disabled)"))
    for (var j = 0; j < adoptLegacy.length; j++)
      parts.push("left-over settings in " + String(adoptLegacy[j].file).split("/").pop())
    return parts.join(" · ")
  }

  function bounded(seconds, argv) {
    return ["timeout", "-k", "2", String(seconds)].concat(argv)
  }

  function refreshAdopt() {
    if (!adoptProc.running && !adoptAction.running) adoptProc.running = true
  }

  function receiveAdopt(raw) {
    try {
      var data = JSON.parse(raw)
      if (data.error) { adoptStatus = data.error; return }
      adoptOthers = data.others || []
      adoptLegacy = data.legacy || []
      adoptRemoveHint = (data.remove_hint || []).join(" · ")
      adoptStatus = ""
    } catch (error) { adoptStatus = "Could not check for other input tools." }
  }

  function runAdopt(action, pluginId) {
    if (adoptAction.running) return
    adoptStatus = action === "backup" ? "Backing up…"
      : action === "import" ? "Backing up, then importing…" : "Backing up, then disabling…"
    var args = ["python3", "-B", root.adoptBackend, action]
    if (pluginId) args.push(pluginId)
    adoptAction.command = root.bounded(60, args)
    adoptAction.running = true
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  // Right-click keeps the original per-tool shortcut: on the Trackpad tab it
  // toggles the touchpad, elsewhere it just opens the panel.
  function togglePrimaryDevice() {
    var toggle = root.bodyFunction("togglePrimary")
    if (toggle) toggle()
    else root.toggle()
  }

  Component.onCompleted: { detectDevices(); refreshAdopt() }

  onOpenedChanged: {
    if (opened) { detectDevices(); refreshAdopt() }
  }

  Process {
    id: adoptProc
    command: root.bounded(20, ["python3", "-B", root.adoptBackend, "status"])
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.receiveAdopt(String(text))
    }
    onExited: function(code, status) {
      if (code !== 0 && root.adoptStatus === "") root.adoptStatus = "Could not check for other input tools."
    }
  }

  Process {
    id: adoptAction
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        try {
          var data = JSON.parse(String(text))
          if (data.error) root.adoptStatus = data.error
          else if (data.disabled) root.adoptStatus = "Disabled " + data.disabled + " · uninstall it with: " + data.uninstall_hint
          else if (data.actions) root.adoptStatus = data.actions.length ? "Imported: " + data.actions.join(", ") : "Nothing left to import."
          else root.adoptStatus = "Backed up to " + data.folder
        } catch (error) { root.adoptStatus = "That action did not finish." }
      }
    }
    onExited: function(code, status) { Qt.callLater(function() { root.refreshAdopt() }) }
  }

  readonly property string adoptBackend: decodeURIComponent(String(Qt.resolvedUrl("adopt.py")).replace(/^file:\/\//, ""))

  Process {
    id: detectProc
    command: ["python3", "-B", root.deviceBackend]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.receiveDevices(String(text))
    }
    onExited: function(code, status) {
      if (code !== 0 && root.deviceStatus === "") root.deviceStatus = "Could not read input devices."
    }
  }

  Process {
    id: logoWriter
    onExited: function(exitCode, exitStatus) {
      if (exitCode !== 0) root.deviceStatus = "Could not change the bar icon."
    }
  }

  readonly property string deviceBackend: decodeURIComponent(String(Qt.resolvedUrl("devices.py")).replace(/^file:\/\//, ""))

  TextMetrics {
    id: logoMetrics
    text: "ThinkPad"
    font.family: "Liberation Sans"
    font.pixelSize: Style.bar.iconFont
    font.bold: true
    font.italic: true
  }

  // ---- Bar icon ----
  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    tooltipText: root.bothDevices ? "Touchpad and TrackPoint"
      : root.hasTrackPoint ? "TrackPoint"
      : "Touchpad"
    // The wordmark and color logo are wider than the square icon slot.
    fixedWidth: vertical || root.logo === "dot" ? -1
      : root.logo === "color" ? colorLogoWidth + Style.space(12)
      : Math.ceil(logoMetrics.advanceWidth) + Style.space(12)
    readonly property int colorLogoHeight: Math.round(Style.bar.iconFont * 1.15)
    // thinkpad-color.svg is 768 x 274
    readonly property int colorLogoWidth: Math.ceil(colorLogoHeight * 768 / 274)
    iconComponent: Component {
      Item {
        Text {
          anchors.centerIn: parent
          visible: root.logo === "wordmark"
          text: logoMetrics.text
          color: "#e2231a"
          font: logoMetrics.font
        }
        Rectangle {
          anchors.centerIn: parent
          visible: root.logo === "dot"
          width: Math.round(Style.bar.iconFont * 0.8)
          height: width
          radius: width / 2
          color: "#e2231a"
        }
        Image {
          anchors.centerIn: parent
          visible: root.logo === "color"
          source: root.logo === "color" ? Qt.resolvedUrl("thinkpad-color.svg") : ""
          width: button.colorLogoWidth
          height: button.colorLogoHeight
          sourceSize: Qt.size(width * 2, height * 2)
          fillMode: Image.PreserveAspectFit
          smooth: true
        }
      }
    }
    onPressed: function(b) {
      if (b === Qt.RightButton) root.togglePrimaryDevice()
      else root.toggle()
    }
  }

  // ---- Popup panel ----
  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(root.bodyWidth)
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(900))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: {
        var blocked = root.bodyFunction("keyboardNavigationBlocked")
        return blocked ? blocked() : false
      }
      onMoveRequested: function(dx, dy) {
        var body = root.activeBody
        if (!body || typeof body.moveCursor !== "function") return
        if (!body.cursorActive) { body.cursorActive = true; return }
        if (dy !== 0) body.moveCursor(dy)
        else if (dx !== 0 && typeof body.moveCursorH === "function") body.moveCursorH(dx)
      }
      onActivateRequested: {
        var activate = root.bodyFunction("activateCursor")
        if (activate && root.activeBody.cursorActive) activate()
      }
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Column {
        id: column
        width: parent.width
        spacing: Style.space(12)

        Text {
          width: parent.width
          text: root.bothDevices ? "Touchpad & TrackPoint" : root.hasTrackPoint ? "TrackPoint" : "Touchpad"
          color: root.bar.foreground
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.title
          font.bold: true
        }

        // Another plugin or a left-over block also manages these devices. Each
        // action backs up first; uninstalling stays the user's own step.
        Column {
          visible: root.adoptNeedsAttention
          width: parent.width
          spacing: Style.space(6)

          Text {
            width: parent.width
            text: "Other tools for these devices"
            color: root.bar.foreground
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.body
            font.bold: true
          }

          Text {
            width: parent.width
            text: root.adoptSummary
            color: Qt.alpha(root.bar.foreground, 0.7)
            wrapMode: Text.Wrap
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
          }

          Row {
            width: parent.width
            spacing: Style.space(4)
            Button {
              text: "Back up"
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
              bordered: true
              focusable: true
              onClicked: root.runAdopt("backup")
            }
            Button {
              visible: root.adoptEnabledOthers
              text: "Back up & disable"
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
              bordered: true
              focusable: true
              onClicked: root.runAdopt("disable", root.adoptOthers[0].id)
            }
            Button {
              text: "Back up & import"
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
              bordered: true
              focusable: true
              onClicked: root.runAdopt("import")
            }
          }

          Text {
            visible: root.adoptRemoveHint !== ""
            width: parent.width
            text: "Uninstall it yourself when you are ready: " + root.adoptRemoveHint
            color: Qt.alpha(root.bar.foreground, 0.6)
            wrapMode: Text.Wrap
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
          }

          Text {
            visible: root.adoptStatus !== ""
            width: parent.width
            text: root.adoptStatus
            color: Qt.alpha(root.bar.foreground, 0.75)
            wrapMode: Text.Wrap
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
          }

          PanelSeparator { width: parent.width }
        }

        // Device tabs: only worth showing when more than one kind is attached.
        Row {
          visible: root.bothDevices
          width: parent.width
          spacing: Style.space(4)
          Repeater {
            model: root.deviceTabModel
            Controls.Button {
              id: deviceTab
              required property var modelData
              width: (column.width - Style.space(4) * (root.deviceTabModel.length - 1)) / Math.max(1, root.deviceTabModel.length)
              height: Style.space(34)
              text: modelData.label
              Accessible.name: modelData.label + " tab"
              property bool selected: root.activeDeviceTab === modelData.key
              onClicked: root.changeDeviceTab(modelData.key)
              contentItem: Text {
                text: deviceTab.text
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.body
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
              }
              background: Rectangle {
                color: deviceTab.selected ? Style.selectedFillFor(root.bar.foreground, Color.accent)
                                          : Style.hoverFillFor(root.bar.foreground, Color.accent)
                border.width: 1
                border.color: deviceTab.selected || deviceTab.activeFocus
                  ? Color.accent : Qt.alpha(root.bar.foreground, 0.2)
              }
            }
          }
        }

        Text {
          visible: root.deviceStatus !== ""
          width: parent.width
          text: root.deviceStatus
          color: Color.urgent
          wrapMode: Text.Wrap
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
        }

        // Device tabs host the ported Trackpad and TrackPoint controls.
        Loader {
          id: deviceBody
          width: parent.width
          sourceComponent: root.activeDeviceTab === "trackpoint" ? trackPointBody : trackpadBody
        }

        Component {
          id: trackpadBody
          TrackpadPanel {
            bar: root.bar
            panelOpen: root.opened
            keyCatcher: keyCatcher
            onCloseRequested: root.close()
            onSwitchPanelRequested: function(direction) { root.switchPanel(direction) }
          }
        }

        Component {
          id: trackPointBody
          TrackPointPanel {
            bar: root.bar
            panelOpen: root.opened
            keyCatcher: keyCatcher
            logo: root.logo
            onCloseRequested: root.close()
            onSwitchPanelRequested: function(direction) { root.switchPanel(direction) }
            onLogoRequested: function(value) { root.setLogo(value) }
          }
        }

        Text {
          visible: root.releaseVersion !== ""
          width: parent.width
          text: "Touchpad Tool " + root.releaseVersion
          color: Qt.alpha(root.bar.foreground, 0.5)
          horizontalAlignment: Text.AlignRight
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
        }
      }
    }
  }
}
