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
    activeDeviceTab = tab
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  Component.onCompleted: detectDevices()

  onOpenedChanged: {
    if (opened) detectDevices()
  }

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
    onPressed: function(b) { root.toggle() }
  }

  // ---- Popup panel ----
  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(360))
    contentHeight: panel.fittedContentHeight(column.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
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
          Column {
            width: parent ? parent.width : 0
            spacing: Style.space(8)
            Text {
              text: "Trackpad"
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.body
            }
            Text {
              width: parent.width
              text: root.touchpads.length ? root.touchpads.join(", ") : "No trackpad detected."
              color: Qt.alpha(root.bar.foreground, 0.65)
              wrapMode: Text.Wrap
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
            }
          }
        }

        Component {
          id: trackPointBody
          Column {
            width: parent ? parent.width : 0
            spacing: Style.space(8)
            Text {
              text: "TrackPoint"
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.body
            }
            Text {
              width: parent.width
              text: root.trackpoints.length ? root.trackpoints.join(", ") : "No TrackPoint detected."
              color: Qt.alpha(root.bar.foreground, 0.65)
              wrapMode: Text.Wrap
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
            }
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
