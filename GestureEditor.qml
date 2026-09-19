pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls

FocusScope {
  id: editor
  required property color foreground
  required property color accent
  required property string fontFamily
  property real uiScale: 1
  property var draft: ({enabled: false, fingers: 3, distance: 300, invert: false, overview: false})
  property var companion: ({installed: false, message: "Checking Trackpad Plus overview…"})
  property bool previewBusy: false
  property string previewText: ""
  readonly property bool companionSelected: draft.overview_provider === "trackpad-plus"
  property var hymission: ({available: false, message: "Checking HyMission…"})
  property bool busy: false
  property bool canEdit: false
  property bool canRestore: false
  property string statusText: "Loading gesture settings…"
  property string errorText: ""
  signal applyRequested(var settings)
  signal restoreRequested()
  signal refreshRequested()
  signal backRequested()
  signal hymissionInfoRequested()
  signal previewRequested()
  signal overviewStatusRequested()
  implicitHeight: contents.implicitHeight

  // Enter the FocusScope through a usable control; even while loading, keep
  // Escape available on the scope itself so keyboard users cannot get stuck.
  function beginEditing() {
    if (enableAction.enabled) enableAction.forceActiveFocus(Qt.TabFocusReason)
    else if (reloadAction.enabled) reloadAction.forceActiveFocus(Qt.TabFocusReason)
    else forceActiveFocus(Qt.TabFocusReason)
  }

  function load(settings) {
    var next = JSON.parse(JSON.stringify(settings))
    next.overview = settings.overview === true
    next.overview_provider = settings.overview_provider || "hymission"
    draft = next
    distanceInput.text = Qt.binding(function() { return String(distanceSpinner.value) })
  }
  function change(key, value) {
    if (draft[key] === value) return
    var next = JSON.parse(JSON.stringify(draft))
    next[key] = value
    draft = next
  }
  function providerDescription() {
    if (companionSelected) {
      if (companion.message) return companion.message
      if (companion.installed) return "A separate Trackpad Plus window shows workspaces on this monitor. Test it first; Escape closes it. Apply connects swipe up and down."
      return "Update or reinstall Trackpad Plus to include the overview companion."
    }
    if (hymission.available) return "Powered by HyMission. Swipe up with " + draft.fingers + " fingers to see your workspaces; swipe down to return."
    return hymission.message || "Install and load HyMission to enable overview."
  }
  function apply() {
    if (distanceInput.acceptableInput) change("distance", Number(distanceInput.text))
    if (canEdit && !busy && distanceInput.acceptableInput) applyRequested(JSON.parse(JSON.stringify(draft)))
  }
  Keys.onEscapePressed: backRequested()

  component Label: Text {
    color: editor.foreground
    font.family: editor.fontFamily
    font.pixelSize: 13 * editor.uiScale
    wrapMode: Text.WordWrap
  }
  component Action: Button {
    id: control
    property bool selected: false
    implicitHeight: 34 * editor.uiScale
    padding: 8 * editor.uiScale
    contentItem: Label {
      text: control.text
      horizontalAlignment: Text.AlignHCenter
      verticalAlignment: Text.AlignVCenter
      opacity: control.enabled ? 1 : 0.4
    }
    background: Rectangle {
      color: control.selected || control.hovered ? Qt.alpha(editor.accent, 0.18) : Qt.alpha(editor.foreground, 0.04)
      border.width: control.activeFocus ? 2 : 1
      border.color: control.activeFocus || control.selected ? editor.accent : Qt.alpha(editor.foreground, 0.2)
    }
  }
  component Divider: Rectangle {
    width: parent.width
    height: 1
    color: Qt.alpha(editor.foreground, 0.12)
  }

  Column {
    id: contents
    width: parent.width
    spacing: 12 * editor.uiScale
    Label {
      width: parent.width
      text: "Workspace gestures · all trackpads"
      font.bold: true
    }
    Label {
      width: parent.width
      text: "Swipe left or right to move between workspaces. Changes take effect when you apply."
      opacity: 0.7
    }
    Row {
      width: parent.width
      spacing: 6 * editor.uiScale
      Action {
        id: enableAction
        objectName: "gestureEnable"
        width: (parent.width - parent.spacing) / 2
        text: "Workspace swipe"
        selected: editor.draft.enabled
        enabled: editor.canEdit && !editor.busy
        Accessible.name: "Workspace swipe " + (editor.draft.enabled ? "on" : "off")
        onClicked: editor.change("enabled", !editor.draft.enabled)
      }
      Action {
        objectName: "gestureInvert"
        width: (parent.width - parent.spacing) / 2
        text: "Reverse direction"
        selected: editor.draft.invert
        enabled: editor.canEdit && editor.draft.enabled && !editor.busy
        Accessible.name: "Reverse workspace swipe direction " + (editor.draft.invert ? "on" : "off")
        onClicked: editor.change("invert", !editor.draft.invert)
      }
    }
    Row {
      width: parent.width
      spacing: 6 * editor.uiScale
      Repeater {
        model: [3, 4]
        Action {
          required property int modelData
          width: (contents.width - 6 * editor.uiScale) / 2
          text: modelData + " fingers"
          selected: editor.draft.fingers === modelData
          enabled: editor.canEdit && (editor.draft.enabled || editor.draft.overview) && !editor.busy
          onClicked: editor.change("fingers", modelData)
        }
      }
    }
    Item {
      width: parent.width
      height: 34 * editor.uiScale
      Label {
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        text: "Swipe distance"
      }
      SpinBox {
        id: distanceSpinner
        objectName: "gestureDistance"
        anchors.right: parent.right
        width: 115 * editor.uiScale
        height: parent.height
        from: 50
        to: 2000
        stepSize: 10
        value: editor.draft.distance
        editable: true
        live: false
        wheelEnabled: false
        enabled: editor.canEdit && editor.draft.enabled && !editor.busy
        Accessible.name: "Workspace swipe distance"
        leftPadding: 8 * editor.uiScale
        rightPadding: 24 * editor.uiScale
        onValueModified: if (!editor.busy && editor.canEdit && editor.draft.enabled) editor.change("distance", value)
        textFromValue: function(value, locale) { return String(value) }
        valueFromText: function(text, locale) { return Number(text) }
        validator: IntValidator { bottom: 50; top: 2000 }
        function largeStep(event) {
          if (!(event.modifiers & Qt.ShiftModifier) || (event.key !== Qt.Key_Up && event.key !== Qt.Key_Down)) return
          var current = distanceInput.acceptableInput ? Number(distanceInput.text) : value
          editor.change("distance", Math.max(from, Math.min(to, current + (event.key === Qt.Key_Up ? 100 : -100))))
          event.accepted = true
        }
        Keys.onPressed: function(event) { largeStep(event) }
        contentItem: TextInput {
          id: distanceInput
          objectName: "gestureDistanceInput"
          text: String(distanceSpinner.value)
          color: editor.foreground
          font.family: editor.fontFamily
          font.pixelSize: 13 * editor.uiScale
          verticalAlignment: Text.AlignVCenter
          selectByMouse: true
          clip: true
          validator: distanceSpinner.validator
          Keys.onPressed: function(event) { distanceSpinner.largeStep(event) }
        }
        background: Rectangle {
          color: Qt.alpha(editor.foreground, 0.04)
          border.width: 1
          border.color: distanceSpinner.activeFocus ? editor.accent : Qt.alpha(editor.foreground, 0.2)
          opacity: distanceSpinner.enabled ? 1 : 0.4
        }
        up.indicator: Label {
          x: distanceSpinner.width - width
          width: 24 * editor.uiScale
          height: distanceSpinner.height / 2
          text: "▴"
          horizontalAlignment: Text.AlignHCenter
          verticalAlignment: Text.AlignVCenter
        }
        down.indicator: Label {
          x: distanceSpinner.width - width
          y: distanceSpinner.height / 2
          width: 24 * editor.uiScale
          height: distanceSpinner.height / 2
          text: "▾"
          horizontalAlignment: Text.AlignHCenter
          verticalAlignment: Text.AlignVCenter
        }
      }
    }
    Label {
      width: parent.width
      text: "Lower values cover a workspace with less finger travel. Use ↑/↓ for 10-unit steps; Shift for 100. Also affects touchscreen workspace swipes."
      opacity: 0.7
    }
    Divider {}
    Label { width: parent.width; text: "Overview provider" }
    Row {
      width: parent.width
      spacing: 6 * editor.uiScale
      Action {
        objectName: "providerTrackpadPlus"
        width: (parent.width - parent.spacing) / 2
        text: "Trackpad Plus"
        selected: editor.companionSelected
        enabled: editor.canEdit && !editor.busy && !editor.previewBusy
        onClicked: editor.change("overview_provider", "trackpad-plus")
      }
      Action {
        objectName: "providerHyMission"
        width: (parent.width - parent.spacing) / 2
        text: "HyMission"
        selected: !editor.companionSelected
        enabled: editor.canEdit && !editor.busy && !editor.previewBusy
        onClicked: editor.change("overview_provider", "hymission")
      }
    }
    Action {
      objectName: "gestureOverview"
      width: parent.width
      text: "Swipe up for overview"
      selected: editor.draft.overview
      enabled: editor.canEdit && !editor.busy && ((editor.companionSelected ? editor.companion.installed && !editor.companion.error : editor.hymission.available) || editor.draft.overview)
      Accessible.name: "Workspace overview " + (editor.draft.overview ? "on" : "off")
      onClicked: editor.change("overview", !editor.draft.overview)
    }
    Label {
      width: parent.width
      text: editor.providerDescription()
      opacity: 0.7
    }
    Action {
      objectName: "hymissionInfo"
      visible: !editor.companionSelected
      width: parent.width
      text: editor.hymission.supported === false ? "HyMission compatibility ↗"
        : editor.hymission.available ? "About HyMission ↗" : "Install HyMission ↗"
      onClicked: editor.hymissionInfoRequested()
    }
    Row {
      visible: editor.companionSelected
      width: parent.width
      spacing: 6 * editor.uiScale
      Action {
        objectName: "overviewPreview"
        width: (parent.width - parent.spacing) / 2
        text: editor.previewBusy ? "Checking…" : "Test overview"
        enabled: editor.companion.installed && !editor.busy && !editor.previewBusy
        onClicked: editor.previewRequested()
      }
      Action {
        objectName: "overviewStatus"
        width: (parent.width - parent.spacing) / 2
        text: "Check status"
        enabled: !editor.busy && !editor.previewBusy
        onClicked: editor.overviewStatusRequested()
      }
    }
    Label {
      visible: editor.companionSelected && editor.previewText !== ""
      width: parent.width
      text: editor.previewText
      opacity: 0.7
    }
    Divider {}
    Label {
      width: parent.width
      text: editor.busy ? "Working…" : editor.errorText || editor.statusText
      color: editor.errorText ? editor.accent : editor.foreground
      opacity: 0.8
    }
    Row {
      width: parent.width
      spacing: 6 * editor.uiScale
      Action {
        objectName: "gestureApply"
        width: (parent.width - parent.spacing) / 2
        text: "Apply gestures"
        enabled: editor.canEdit && !editor.busy && distanceInput.acceptableInput
        onClicked: editor.apply()
      }
      Action {
        objectName: "gestureRestore"
        width: (parent.width - parent.spacing) / 2
        text: "Restore original"
        enabled: editor.canRestore && !editor.busy
        onClicked: editor.restoreRequested()
      }
    }
    Action {
      id: reloadAction
      objectName: "gestureReload"
      width: parent.width
      text: "Reload settings"
      enabled: !editor.busy
      onClicked: editor.refreshRequested()
    }
  }
}
