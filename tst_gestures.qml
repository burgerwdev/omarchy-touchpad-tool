import QtQuick
import QtTest

Item {
  width: 380
  height: 1000
  GestureEditor {
    id: editor
    width: 340
    foreground: "#d3c6aa"
    accent: "#83b4ae"
    fontFamily: "monospace"
    canEdit: true
  }
  Item { id: outsideFocus; focus: true }
  SignalSpy { id: previewSpy; target: editor; signalName: "previewRequested" }
  SignalSpy { id: statusSpy; target: editor; signalName: "overviewStatusRequested" }
  SignalSpy { id: infoSpy; target: editor; signalName: "hymissionInfoRequested" }
  SignalSpy { id: backSpy; target: editor; signalName: "backRequested" }
  SignalSpy { id: applySpy; target: editor; signalName: "applyRequested" }
  SignalSpy { id: restoreSpy; target: editor; signalName: "restoreRequested" }
  TestCase {
    name: "GestureEditor"
    when: windowShown
    function init() {
      editor.busy = false
      editor.canEdit = true
      editor.canRestore = true
      editor.errorText = ""
      editor.hymission = {available: false, message: "Install and load HyMission"}
      editor.companion = {installed: true, reachable: false}
      editor.previewBusy = false
      editor.previewText = ""
      previewSpy.clear()
      statusSpy.clear()
      infoSpy.clear()
      editor.load({enabled: true, fingers: 3, distance: 300, invert: false})
      outsideFocus.forceActiveFocus()
      backSpy.clear()
      applySpy.clear()
      restoreSpy.clear()
      waitForRendering(editor)
    }
    function test_keyboard_entry_tab_navigation_and_escape() {
      verify(!editor.activeFocus)
      editor.beginEditing()
      verify(editor.activeFocus)
      verify(findChild(editor, "gestureEnable").activeFocus)
      keyClick(Qt.Key_Tab)
      verify(findChild(editor, "gestureInvert").activeFocus)
      keyClick(Qt.Key_Tab, Qt.ShiftModifier)
      verify(findChild(editor, "gestureEnable").activeFocus)
      keyClick(Qt.Key_Space)
      compare(editor.draft.enabled, false)
      keyClick(Qt.Key_Escape)
      compare(backSpy.count, 1)
      outsideFocus.forceActiveFocus()
      verify(!editor.activeFocus)
      editor.beginEditing()
      verify(findChild(editor, "gestureEnable").activeFocus)
      keyClick(Qt.Key_Escape)
      compare(backSpy.count, 2)
    }
    function test_keyboard_entry_unsupported_and_busy_still_allows_escape() {
      editor.canEdit = false
      editor.beginEditing()
      verify(findChild(editor, "gestureReload").activeFocus)
      keyClick(Qt.Key_Escape)
      compare(backSpy.count, 1)
      outsideFocus.forceActiveFocus()
      editor.busy = true
      editor.beginEditing()
      verify(editor.activeFocus)
      keyClick(Qt.Key_Escape)
      compare(backSpy.count, 2)
    }
    function test_optional_overview_dependency_and_install_link() {
      var overview = findChild(editor, "gestureOverview")
      verify(!overview.enabled)
      compare(editor.draft.overview, false)
      mouseClick(findChild(editor, "hymissionInfo"))
      compare(infoSpy.count, 1)
      editor.hymission = {available: true, message: "HyMission loaded"}
      verify(overview.enabled)
      mouseClick(overview)
      compare(editor.draft.overview, true)
      compare(applySpy.count, 0)
      mouseClick(findChild(editor, "gestureApply"))
      compare(applySpy.signalArguments[0][0].overview, true)
      editor.hymission = {available: false, message: "HyMission is not loaded"}
      verify(overview.enabled) // A missing dependency must allow turning it off.
      mouseClick(overview)
      compare(editor.draft.overview, false)
    }
    function test_unsupported_overview_explains_compatibility_and_allows_turning_off() {
      editor.hymission = {available: false, supported: false, message: "HyMission overview is unavailable on ARM64"}
      compare(findChild(editor, "hymissionInfo").text, "HyMission compatibility ↗")
      verify(!findChild(editor, "gestureOverview").enabled)
      verify(findChild(editor, "gestureEnable").enabled)
      editor.load({enabled: true, fingers: 3, distance: 300, invert: false, overview: true})
      verify(findChild(editor, "gestureOverview").enabled)
      mouseClick(findChild(editor, "gestureOverview"))
      compare(editor.draft.overview, false)
      verify(!findChild(editor, "gestureOverview").enabled)
    }
    function test_explicit_provider_preview_preserves_draft() {
      compare(editor.draft.overview_provider, "hymission")
      editor.change("distance", 480)
      mouseClick(findChild(editor, "providerTrackpadPlus"))
      compare(editor.draft.overview_provider, "trackpad-plus")
      verify(findChild(editor, "gestureOverview").enabled)
      mouseClick(findChild(editor, "gestureOverview"))
      waitForRendering(editor)
      mouseClick(findChild(editor, "overviewPreview"))
      compare(previewSpy.count, 1)
      compare(applySpy.count, 0)
      editor.companion = {installed: true, reachable: true, protocolCompatible: true, rendered: false}
      editor.previewText = "Rendering is not confirmed"
      compare(editor.draft.distance, 480)
      compare(editor.draft.overview, true)
      mouseClick(findChild(editor, "overviewStatus"))
      compare(statusSpy.count, 1)
      editor.previewBusy = true
      verify(!findChild(editor, "overviewPreview").enabled)
      verify(!findChild(editor, "providerHyMission").enabled)
      editor.previewBusy = false
      waitForRendering(editor)
      mouseClick(findChild(editor, "gestureApply"))
      compare(applySpy.signalArguments[0][0].overview_provider, "trackpad-plus")
    }
    function test_saved_companion_selection_survives_missing_dependency() {
      editor.load({enabled: true, fingers: 3, distance: 300, invert: false,
                   overview: true, overview_provider: "trackpad-plus"})
      editor.companion = {installed: false}
      verify(findChild(editor, "gestureOverview").enabled)
      verify(!findChild(editor, "overviewPreview").enabled)
      mouseClick(findChild(editor, "gestureOverview"))
      compare(editor.draft.overview, false)
      compare(editor.draft.overview_provider, "trackpad-plus")
    }
    function test_preview_and_explicit_apply() {
      mouseClick(findChild(editor, "gestureInvert"))
      compare(editor.draft.invert, true)
      compare(applySpy.count, 0)
      mouseClick(findChild(editor, "gestureApply"))
      compare(applySpy.count, 1)
      compare(applySpy.signalArguments[0][0].invert, true)
    }
    function test_distance_typing_and_shift_arrows() {
      var input = findChild(editor, "gestureDistanceInput")
      input.forceActiveFocus()
      input.selectAll()
      keyClick(Qt.Key_4); keyClick(Qt.Key_7); keyClick(Qt.Key_0)
      keyClick(Qt.Key_Up, Qt.ShiftModifier)
      compare(editor.draft.distance, 570)
      keyClick(Qt.Key_Down)
      compare(editor.draft.distance, 560)
      input.selectAll()
      keyClick(Qt.Key_6); keyClick(Qt.Key_4); keyClick(Qt.Key_0)
      mouseClick(findChild(editor, "gestureApply"))
      compare(applySpy.count, 1)
      compare(applySpy.signalArguments[0][0].distance, 640)
    }
    function test_reload_replaces_uncommitted_distance_text() {
      var input = findChild(editor, "gestureDistanceInput")
      input.forceActiveFocus()
      input.selectAll()
      keyClick(Qt.Key_6); keyClick(Qt.Key_4); keyClick(Qt.Key_0)
      compare(input.text, "640")
      editor.load({enabled: true, fingers: 3, distance: 300, invert: false})
      compare(input.text, "300")
      editor.apply()
      compare(applySpy.signalArguments[0][0].distance, 300)
      editor.change("distance", 500)
      compare(input.text, "500")
    }
    function test_invalid_input_busy_and_unsupported_do_not_apply() {
      var input = findChild(editor, "gestureDistanceInput")
      input.forceActiveFocus()
      input.selectAll()
      keyClick(Qt.Key_Backspace)
      editor.apply()
      compare(applySpy.count, 0)
      editor.load({enabled: true, fingers: 3, distance: 300, invert: false})
      editor.busy = true
      editor.apply()
      compare(applySpy.count, 0)
      editor.busy = false
      editor.canEdit = false
      editor.apply()
      compare(applySpy.count, 0)
    }
    function test_restore_and_failed_apply_preserve_draft() {
      editor.change("fingers", 4)
      editor.errorText = "Reload failed"
      compare(editor.draft.fingers, 4)
      compare(applySpy.count, 0)
      mouseClick(findChild(editor, "gestureRestore"))
      compare(restoreSpy.count, 1)
      verify(editor.implicitHeight > 0)
      verify(editor.implicitHeight < 1000)
    }
  }
}
