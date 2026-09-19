import QtQuick
import QtTest
import "Curve.js" as Curve

Rectangle {
  width: 470
  height: 760
  color: "#171b22"
  CurveEditor {
    id: editor
    x: 20
    y: 20
    width: 430
    foreground: "#e7edf4"
    accent: "#82b8b0"
    fontFamily: "sans-serif"
    onApplyRequested: function(value) { saved = Curve.copy(value) }
  }
  SignalSpy { id: applied; target: editor; signalName: "applyRequested" }
  SignalSpy { id: restored; target: editor; signalName: "restoreRequested" }
  SignalSpy { id: back; target: editor; signalName: "backRequested" }
  TestCase {
    name: "CurveEditor"
    when: windowShown
    function init() {
      editor.saved = {profile: "adaptive", curve: Curve.defaults()}
      editor.gainMaximum = 3.5
      editor.busy = false
      editor.settingsError = ""
      editor.canRestore = false
      editor.begin()
      applied.clear(); restored.clear(); back.clear()
    }
    function test_device_scale_controls_chart_and_gain_inputs() {
      editor.saved = {profile: "custom", curve: {precision: 0.01, start: 0, end: 4, fast: 0.55}}
      editor.begin()
      var original = JSON.stringify(editor.draft)
      var plot = findChild(editor, "curvePlot")
      editor.gainMaximum = 1
      compare(plot.py(1), plot.topInset)
      compare(findChild(editor, "curveSpinner3").to, 10000)
      editor.gainMaximum = 3
      compare(plot.py(3), plot.topInset)
      compare(findChild(editor, "curveSpinner3").to, 30000)
      compare(JSON.stringify(editor.draft), original)
      compare(applied.count, 0)
      editor.adjust(3, 9)
      compare(editor.draft.curve.fast, 3)
      editor.gainMaximum = 1
      verify(editor.curveExceedsRange)
      compare(editor.draft.curve.fast, 3)
      editor.choose("mac")
      compare(editor.draft.curve.fast, 1)
      verify(!editor.curveExceedsRange)
    }
    function test_failed_save_is_not_labelled_applied() {
      editor.settingsError = "Compositor unavailable"
      var status = findChild(editor, "curveStatus")
      verify(status.text.indexOf("Compositor unavailable") >= 0)
      verify(status.text.indexOf("Applied") < 0)
    }
    function test_preview_apply_and_restore() {
      editor.choose("mac")
      verify(editor.dirty)
      compare(editor.saved.profile, "adaptive")
      compare(applied.count, 0)
      var apply = findChild(editor, "applyCurve")
      mouseClick(apply)
      compare(applied.count, 1)
      compare(editor.saved.profile, "mac")
      verify(!editor.dirty)
      editor.canRestore = true
      mouseClick(findChild(editor, "restoreCurve"))
      compare(restored.count, 1)
    }
    function test_keyboard_and_pointer_handles() {
      editor.choose("custom")
      wait(50)
      var handle = findChild(editor, "curveHandle0")
      handle.forceActiveFocus()
      keyClick(Qt.Key_Up)
      verify(editor.draft.curve.precision > 0.3)
      var start = findChild(editor, "curveHandle1")
      start.forceActiveFocus()
      keyClick(Qt.Key_Right)
      compare(editor.draft.curve.start, 0.85)
      compare(editor.draft.curve.end, 2.8)
      var end = findChild(editor, "curveHandle2")
      end.forceActiveFocus()
      keyClick(Qt.Key_Left)
      compare(editor.draft.curve.end, 2.75)
      compare(editor.draft.curve.start, 0.85)
      var fast = findChild(editor, "curveHandle3")
      var before = editor.draft.curve.fast
      mouseDrag(fast, fast.width / 2, fast.height / 2, 0, -30)
      verify(editor.draft.curve.fast > before)
      compare(applied.count, 0, "Dragging must not change live acceleration")
      keyClick(Qt.Key_Escape)
      compare(back.count, 1)
    }
    function test_practice_and_busy_state() {
      editor.choose("mac")
      editor.busy = true
      verify(!findChild(editor, "applyCurve").enabled)
      mouseClick(findChild(editor, "practiceTarget"))
      compare(editor.hits, 1)
    }
    function enterNumber(index, text) {
      var field = findChild(editor, "curveNumber" + index)
      mouseClick(field)
      keyClick(Qt.Key_A, Qt.ControlModifier)
      for (var i = 0; i < text.length; i++) keyClick(text.charAt(i))

    }
    function test_spinners_type_arrow_and_apply() {
      editor.choose("custom")
      wait(50)
      enterNumber(0, "0.0648")
      keyClick(Qt.Key_Return)
      compare(editor.draft.curve.precision, 0.0648)
      keyClick(Qt.Key_Up)
      compare(editor.draft.curve.precision, 0.0658)
      keyClick(Qt.Key_Down)
      compare(editor.draft.curve.precision, 0.0648)
      enterNumber(1, "21.00")
      keyClick(Qt.Key_Return)
      compare(editor.draft.curve.start, 0.84)
      keyClick(Qt.Key_Up)
      compare(editor.draft.curve.start, 0.88)
      enterNumber(2, "75.50")
      keyClick(Qt.Key_Return)
      compare(editor.draft.curve.end, 3.02)
      enterNumber(3, "0.5265")
      compare(applied.count, 0)
      mouseClick(findChild(editor, "applyCurve"))
      compare(applied.count, 1)
      compare(editor.saved.curve.fast, 0.5265)
      compare(editor.saved.curve.precision, 0.0648)
    }
    function test_spinners_shift_steps() {
      editor.choose("custom")
      wait(50)
      enterNumber(0, "0.0648")
      keyClick(Qt.Key_Up, Qt.ShiftModifier)
      compare(editor.draft.curve.precision, 0.0748)
      keyClick(Qt.Key_Down, Qt.ShiftModifier)
      compare(editor.draft.curve.precision, 0.0648)
      keyClick(Qt.Key_Up)
      compare(editor.draft.curve.precision, 0.0658)
      enterNumber(1, "21.00")
      keyClick(Qt.Key_Return)
      keyClick(Qt.Key_Up, Qt.ShiftModifier)
      compare(editor.draft.curve.start, 1.24)
      keyClick(Qt.Key_Down, Qt.ShiftModifier)
      compare(editor.draft.curve.start, 0.84)
      enterNumber(0, "0.0150")
      keyClick(Qt.Key_Down, Qt.ShiftModifier)
      compare(editor.draft.curve.precision, 0.01)
      enterNumber(1, "65.00")
      keyClick(Qt.Key_Up, Qt.ShiftModifier)
      compare(editor.draft.curve.start, 2.6)
      compare(applied.count, 0)
      mouseClick(findChild(editor, "applyCurve"))
      compare(editor.saved.curve.start, 2.6)
      compare(editor.saved.curve.precision, 0.01)
    }
    function test_spinners_follow_graph_and_enforce_bounds() {
      editor.choose("custom")
      editor.adjust(0, 0.12)
      compare(findChild(editor, "curveSpinner0").value, 1200)
      wait(50)
      enterNumber(0, "0.0100")
      keyClick(Qt.Key_Return)
      keyClick(Qt.Key_Down)
      compare(editor.draft.curve.precision, 0.01)
      enterNumber(1, "65.00")
      keyClick(Qt.Key_Return)
      keyClick(Qt.Key_Up)
      compare(editor.draft.curve.start, 2.6)
      verify(editor.draft.curve.end - editor.draft.curve.start >= 0.2 - 1e-9)
      editor.adjust(1, 0.812, true)
      editor.adjust(2, 0)
      verify(editor.draft.curve.end - editor.draft.curve.start >= 0.2 - 1e-9)
      mouseClick(findChild(editor, "curveSpinner0").up.indicator)
      compare(editor.draft.curve.precision, 0.011)
      editor.adjust(0, 0)
      compare(editor.draft.curve.precision, 0.01)
      enterNumber(3, "0.0100")
      keyClick(Qt.Key_Return)
      keyClick(Qt.Key_Down)
      compare(editor.draft.curve.fast, 0.01)
      mouseClick(findChild(editor, "applyCurve"))
      compare(editor.saved.curve.precision, 0.01)
      compare(editor.saved.curve.fast, 0.01)
    }
    function test_transition_end_reaches_100_percent() {
      editor.choose("custom")
      wait(50)
      enterNumber(2, "99.00")
      keyClick(Qt.Key_Return)
      compare(editor.draft.curve.end, 3.96)
      keyClick(Qt.Key_Up)
      compare(editor.draft.curve.end, 4)
      keyClick(Qt.Key_Up, Qt.ShiftModifier)
      compare(editor.draft.curve.end, 4)
      mouseClick(findChild(editor, "applyCurve"))
      compare(editor.saved.curve.end, 4)
      editor.begin()
      compare(findChild(editor, "curveSpinner2").value, 10000)
      var end = findChild(editor, "curveHandle2")
      var fast = findChild(editor, "curveHandle3")
      verify(Math.abs(end.y - fast.y) >= 30, "End and fast-swipe hit areas must remain separate")
      mouseDrag(end, end.width / 2, end.height / 2, -40, 0)
      verify(editor.draft.curve.end < 4)
      compare(editor.draft.curve.fast, 1.6)
      editor.adjust(2, 4)
      var before = editor.draft.curve.fast
      mouseDrag(fast, fast.width / 2, fast.height / 2, 0, -20)
      verify(editor.draft.curve.fast > before)
      compare(editor.draft.curve.end, 4)
    }
    function test_visual_layout() {
      editor.choose("mac")
      wait(100)
      verify(editor.implicitHeight < 740)
      var picture = grabImage(editor)
      verify(picture.width > 0)
    }
  }
}
