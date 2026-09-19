pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons

// TrackPoint controls: the body of the TrackPoint tab. The merged panel owns the
// bar icon and the popup, so the icon choice here asks the panel to change its own
// bar entry, and the panel routes open state, keys and popup sizing into this body.
Item {
  id: root
  property var bar: null
  property bool panelOpen: false
  property var keyCatcher: null
  property string logo: "wordmark"
  signal closeRequested()
  signal switchPanelRequested(int direction)
  signal logoRequested(string value)
  property real sensitivity: 0
  property string device: ""
  property string status: ""
  property bool queued: false
  // Helpers sit next to this file whether it runs from the repo or from the
  // installed plugin directory.
  readonly property string helper: decodeURIComponent(String(Qt.resolvedUrl("control.py")).replace(/^file:\/\//, ""))
  // Middle button (the one between the two hard buttons) bound through hypr/bindings.lua
  readonly property string middleHelper: decodeURIComponent(String(Qt.resolvedUrl("middle.py")).replace(/^file:\/\//, ""))
  readonly property var logoOptions: [
    { value: "wordmark", label: "ThinkPad" },
    { value: "dot", label: "Red dot" },
    { value: "color", label: "Color logo" }
  ]
  property bool middleEnabled: false
  property var middleProfiles: ({ "default": {} })
  property string middleProfile: "default"
  property string middleSection: "taps"
  property string middleStatus: ""
  readonly property var middleSections: [
    { value: "taps", label: "Taps" },
    { value: "holds", label: "Holds" },
    { value: "gestures", label: "Gestures" },
    { value: "mods", label: "Modifiers" }
  ]
  readonly property var middleSlots: ({
    taps: [
      { key: "tap", label: "Tap" },
      { key: "double", label: "Double tap" },
      { key: "triple", label: "Triple tap" }
    ],
    holds: [
      { key: "hold", label: "Hold" },
      { key: "double_hold", label: "Double tap + hold" },
      { key: "triple_hold", label: "Triple tap + hold" }
    ],
    gestures: [
      { key: "up", label: "Hold + flick up" },
      { key: "down", label: "Hold + flick down" },
      { key: "left", label: "Hold + flick left" },
      { key: "right", label: "Hold + flick right" }
    ],
    mods: [
      { key: "super", label: "Super + tap" },
      { key: "alt", label: "Alt + tap" },
      { key: "shift", label: "Shift + tap" },
      { key: "ctrl", label: "Ctrl + tap" },
      { key: "super_shift", label: "Super + Shift + tap" },
      { key: "super_alt", label: "Super + Alt + tap" },
      { key: "super_ctrl", label: "Super + Ctrl + tap" },
      { key: "ctrl_alt", label: "Ctrl + Alt + tap" },
      { key: "ctrl_shift", label: "Ctrl + Shift + tap" },
      { key: "alt_shift", label: "Alt + Shift + tap" }
    ]
  })
  // Every preset is a stock Omarchy command; anything else goes in "Custom command…"
  readonly property var middlePresets: [
    { value: "", label: "Nothing" },
    // Menus
    { value: "omarchy-menu toggle root", label: "Omarchy menu" },
    { value: "omarchy-menu toggle apps", label: "Apps menu" },
    { value: "omarchy-menu toggle theme", label: "Theme menu" },
    // Capture
    { value: "omarchy-capture-screenshot", label: "Screenshot" },
    { value: "omarchy-capture-screenrecording --stop-recording || omarchy-menu toggle trigger.capture.screenrecord", label: "Screen recording" },
    { value: "omarchy-capture-text", label: "Extract text (OCR)" },
    { value: "pkill hyprpicker || hyprpicker -a", label: "Color picker" },
    // Input
    { value: "omarchy-shell shell toggle omarchy.clipboard", label: "Clipboard history" },
    { value: "omarchy-shell shell toggle omarchy.emojis", label: "Emoji picker" },
    // Media and audio
    { value: "omarchy-shell media playPause", label: "Play / pause" },
    { value: "omarchy-shell media next", label: "Next track" },
    { value: "omarchy-shell media previous", label: "Previous track" },
    { value: "omarchy-audio-output-volume mute-toggle", label: "Mute audio" },
    { value: "omarchy-audio-input-mute", label: "Mute microphone" },
    // Apps
    { value: "omarchy-launch-terminal", label: "Open terminal" },
    { value: "omarchy-launch-browser", label: "Open browser" },
    { value: "omarchy-launch-nautilus", label: "File manager" },
    { value: "omarchy-launch-editor", label: "Editor" },
    // Window and system
    { value: "omarchy-hyprland-window-pop", label: "Pop window out" },
    { value: "omarchy-system-lock", label: "Lock screen" },
    { value: "omarchy-toggle-nightlight", label: "Toggle nightlight" },
    { value: "omarchy-shell shell toggle omarchy.bluetooth", label: "Bluetooth" },
    // Notifications
    { value: "omarchy-shell notifications showHistory", label: "Notification history" },
    { value: "omarchy-shell notifications dismissAll", label: "Dismiss notifications" },
    { value: "omarchy-toggle-notification-silencing", label: "Silence notifications" },
    { value: "custom", label: "Custom command…" }
  ]
  // App profiles fall back to the default for anything left empty, so empty
  // means "same as default" there and ":" (a shell no-op) blocks the default.
  readonly property var appPresets: [
    { value: "", label: "Same as default" },
    { value: ":", label: "Do nothing" }
  ].concat(middlePresets.slice(1))
  readonly property var activePresets: middleProfile === "default" ? middlePresets : appPresets
  readonly property var profileOptions: {
    var options = [{ value: "default", label: "All apps (default)" }]
    for (var name in middleProfiles)
      if (name !== "default") options.push({ value: name, label: name })
    options.push({ value: "__add", label: "Add focused app…" })
    return options
  }
  readonly property real contentWidth: Style.space(360)

  // Arrow keys nudge the sensitivity, as in the original panel.
  function moveCursor(dx) { if (dx !== 0) root.setSensitivity(root.sensitivity + dx * 0.05) }
  function togglePrimary() {}

  function refresh() {
    if (!reader.running && !writer.running) reader.running = true
    if (!middleReader.running && !middleWriter.running) middleReader.running = true
  }
  function choiceFor(command) {
    for (var i = 0; i < activePresets.length; i++)
      if (activePresets[i].value === command && command !== "custom") return command
    return "custom"
  }
  function commandFor(slot) {
    return (middleProfiles[middleProfile] || {})[slot] || ""
  }
  function runMiddle(args) {
    if (middleWriter.running) return
    middleStatus = "Saving…"
    middleWriter.command = ["python3", middleHelper].concat(args)
    middleWriter.running = true
  }
  function applyMiddle(data) {
    middleEnabled = !!data.enabled
    middleProfiles = data.profiles || { "default": {} }
    if (data.added) middleProfile = data.added
    if (!middleProfiles[middleProfile]) middleProfile = "default"
    // Dropdown assigns its own value on selection, which drops a binding
    profileDropdown.value = middleProfile
  }
  function setSensitivity(value) {
    sensitivity = Math.round(Math.max(-1, Math.min(1, value)) * 100) / 100
    status = "Saving…"
    if (writer.running) { queued = true; return }
    queued = false
    writer.command = ["python3", helper, sensitivity.toFixed(2)]
    writer.running = true
  }
  Component.onCompleted: refresh()
  onPanelOpenChanged: {
    if (!panelOpen) return
    refresh()
    // Start with the profile list folded so it doesn't cover the actions.
    Qt.callLater(function() { profileDropdown.close() })
  }

  Process {
    id: reader
    command: ["python3", root.helper]
    stdout: StdioCollector {
      onStreamFinished: {
        try {
          var data = JSON.parse(text)
          if (data.error) root.status = data.error
          else { root.sensitivity = data.value; root.device = data.device || ""; root.status = "" }
        } catch (e) { root.status = "Could not read sensitivity." }
      }
    }
  }
  Process {
    id: writer
    stdout: StdioCollector {
      onStreamFinished: {
        try {
          var data = JSON.parse(text)
          root.status = data.error ? data.error : "Saved"
        } catch (e) { root.status = "Could not save sensitivity." }
      }
    }
    onExited: function(exitCode, exitStatus) {
      if (exitCode !== 0 && root.status === "Saving…") root.status = "Could not save sensitivity."
      if (root.queued) root.setSensitivity(root.sensitivity)
    }
  }
  Process {
    id: middleReader
    command: ["python3", root.middleHelper]
    stdout: StdioCollector {
      onStreamFinished: {
        try {
          var data = JSON.parse(text)
          if (data.error) root.middleStatus = data.error
          else { root.applyMiddle(data); root.middleStatus = "" }
        } catch (e) { root.middleStatus = "Could not read middle button." }
      }
    }
  }
  Process {
    id: middleWriter
    stdout: StdioCollector {
      onStreamFinished: {
        try {
          var data = JSON.parse(text)
          if (data.error) root.middleStatus = data.error
          else {
            root.applyMiddle(data)
            root.middleStatus = data.added ? "Added " + data.added : "Saved"
          }
        } catch (e) { root.middleStatus = "Could not save middle button." }
      }
    }
    onExited: function(exitCode, exitStatus) {
      if (exitCode !== 0 && root.middleStatus === "Saving…") root.middleStatus = "Could not save middle button."
    }
  }

  function setLogo(value) {
    if (value === logo) return
    // The merged panel owns this widget's bar entry, so it performs the change.
    root.logoRequested(value)
  }

  ScrollView {
    anchors.fill: parent
    clip: true
    contentWidth: availableWidth

    Column {
      id: content
      width: parent.width
      spacing: Style.space(12)
        Text {
          text: "TrackPoint"
          color: root.bar.foreground
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.title
          font.bold: true
        }
        Text {
          text: "Pointer sensitivity  " + (slider.dragging ? slider.liveValue : root.sensitivity).toFixed(2)
          color: root.bar.foreground
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.body
        }
        PanelSlider {
          id: slider
          width: parent.width
          bar: root.bar
          minimum: -1
          maximum: 1
          step: 0.05
          value: root.sensitivity
          fillColor: "#e55768"
          knobColor: "#e55768"
          onReleased: function(v) { root.setSensitivity(v) }
        }
        Item {
          width: parent.width
          implicitHeight: slower.implicitHeight
          Text {
            id: slower
            text: "Slower"
            color: root.bar.foreground
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
          }
          Text {
            anchors.right: parent.right
            text: "Faster"
            color: root.bar.foreground
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
          }
        }
        Button {
          text: "Reset to default"
          foreground: root.bar.foreground
          fontFamily: root.bar.fontFamily
          bordered: true
          focusable: true
          onClicked: root.setSensitivity(0)
        }
        Text {
          width: parent.width
          text: root.status || "Release to apply · Saved for next login"
          wrapMode: Text.WordWrap
          color: root.bar.foreground
          opacity: 0.7
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
        }

        Text {
          text: "Bar icon"
          color: root.bar.foreground
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.body
        }
        ButtonGroup {
          options: root.logoOptions
          value: root.logo
          spacing: Style.space(4)
          foreground: root.bar.foreground
          fontFamily: root.bar.fontFamily
          fontSize: Style.font.caption
          focusable: false
          onChanged: function(v) { root.setLogo(v) }
        }

        PanelSeparator { width: parent.width }

        Item {
          width: parent.width
          implicitHeight: Math.max(middleTitle.implicitHeight, turnOff.implicitHeight)
          Text {
            id: middleTitle
            anchors.verticalCenter: parent.verticalCenter
            text: "Middle button"
            color: root.bar.foreground
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.title
            font.bold: true
          }
          Button {
            id: turnOff
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            visible: root.middleEnabled
            text: "Turn off"
            foreground: root.bar.foreground
            fontFamily: root.bar.fontFamily
            bordered: true
            focusable: true
            onClicked: root.runMiddle(["disable"])
          }
        }

        // Nothing in the Hyprland config changes until the user opts in here
        Column {
          visible: !root.middleEnabled
          width: parent.width
          spacing: Style.space(8)
          Text {
            width: parent.width
            text: "Run your own actions on taps, holds and flicks of the middle button. Enabling adds a marked block to ~/.config/hypr/bindings.lua and turns off the TrackPoint's hold-to-scroll. Turn off removes the block and restores scrolling."
            wrapMode: Text.WordWrap
            color: root.bar.foreground
            opacity: 0.7
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
          }
          Button {
            text: "Enable middle button actions"
            foreground: root.bar.foreground
            fontFamily: root.bar.fontFamily
            bordered: true
            focusable: true
            onClicked: root.runMiddle(["enable"])
          }
        }

        Column {
          visible: root.middleEnabled
          width: parent.width
          spacing: Style.space(12)

          Row {
            width: parent.width
            spacing: Style.space(6)
            Dropdown {
              id: profileDropdown
              width: parent.width - (removeApp.visible ? removeApp.width + parent.spacing : 0)
              showLabel: false
              options: root.profileOptions
              Component.onCompleted: value = root.middleProfile
              onChanged: function(v) {
                if (v === "__add") {
                  value = root.middleProfile
                  root.runMiddle(["add-app"])
                } else {
                  root.middleProfile = v
                }
              }
            }
            Button {
              id: removeApp
              visible: root.middleProfile !== "default"
              text: "Remove"
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
              bordered: true
              focusable: true
              onClicked: root.runMiddle(["remove-app", root.middleProfile])
            }
          }

          ButtonGroup {
            options: root.middleSections
            value: root.middleSection
            spacing: Style.space(4)
            foreground: root.bar.foreground
            fontFamily: root.bar.fontFamily
            fontSize: Style.font.caption
            focusable: false
            onChanged: function(v) { root.middleSection = v }
          }

          Repeater {
            id: slotRepeater
            model: root.middleSlots[root.middleSection]
            delegate: Column {
              id: slotRow
              required property var modelData
              readonly property string slot: modelData.key
              readonly property string command: root.commandFor(slot)
              property bool editingCustom: false
              readonly property string choice: editingCustom ? "custom" : root.choiceFor(command)
              width: parent ? parent.width : 0
              spacing: Style.space(4)

              function closeDropdown() { slotDropdown.close() }
              function sync() {
                // Dropdown assigns its own value on selection, which drops a binding
                slotDropdown.value = choice
                if (choice === "custom" && !editingCustom) slotField.text = command
              }
              onChoiceChanged: sync()
              onCommandChanged: { editingCustom = false; sync() }
              Component.onCompleted: sync()
              // Each action row folds its own dropdown when the panel closes, so
              // no stale menu is left covering the next panel.
              Connections {
                target: root
                function onPanelOpenChanged() { if (!root.panelOpen) slotDropdown.close() }
              }

              Item {
                width: parent.width
                implicitHeight: slotDropdown.implicitHeight
                Text {
                  anchors.left: parent.left
                  anchors.verticalCenter: parent.verticalCenter
                  width: parent.width * 0.42
                  text: slotRow.modelData.label
                  elide: Text.ElideRight
                  color: root.bar.foreground
                  font.family: root.bar.fontFamily
                  font.pixelSize: Style.font.caption
                }
                Dropdown {
                  id: slotDropdown
                  anchors.right: parent.right
                  width: parent.width * 0.58
                  showLabel: false
                  options: root.activePresets
                  onChanged: function(v) {
                    if (v === "custom") {
                      slotRow.editingCustom = true
                      slotField.text = slotRow.command
                      slotField.forceActiveFocus()
                    } else {
                      slotRow.editingCustom = false
                      root.runMiddle(["set", root.middleProfile, slotRow.slot, v])
                    }
                  }
                }
              }
              Row {
                visible: slotRow.choice === "custom"
                width: parent.width
                spacing: Style.space(6)
                TextField {
                  id: slotField
                  width: parent.width - saveCustom.width - parent.spacing
                  placeholderText: "Command to run"
                  foreground: root.bar.foreground
                  verticalPadding: Style.space(4)
                  onAccepted: root.runMiddle(["set", root.middleProfile, slotRow.slot, text])
                  Keys.onEscapePressed: root.closeRequested()
                }
                Button {
                  id: saveCustom
                  text: "Save"
                  foreground: root.bar.foreground
                  fontFamily: root.bar.fontFamily
                  bordered: true
                  focusable: true
                  onClicked: root.runMiddle(["set", root.middleProfile, slotRow.slot, slotField.text])
                }
              }
            }
          }
        }

        Text {
          width: parent.width
          visible: root.middleEnabled || root.middleStatus !== ""
          text: root.middleStatus || (root.middleSection === "mods"
            ? "Hold the modifier keys, then tap the middle button · runs instantly"
            : "Hold 0.4 s · taps 0.3 s apart count together · flick while holding for gestures · app profiles override the default")
          wrapMode: Text.WordWrap
          color: root.bar.foreground
          opacity: 0.7
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
        }
      }
    }
}
