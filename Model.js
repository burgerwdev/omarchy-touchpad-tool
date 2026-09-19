// Trackpad editor value handling: clamps and human labels for the two sliders.
// Device discovery and every settings write happen in Python (devices.py and
// trackpads.py), so this file only shapes the values the panel shows and stores.

// Fine steps below 0.1 are useful on sensitive trackpads.
function clampScrollFactor(value) {
  var v = Number(value)
  if (!isFinite(v)) v = 0.4
  if (v < 0.01) v = 0.01
  if (v > 1.0) v = 1.0
  return Math.round(v * 100) / 100
}

// Label for the current scroll speed. Rendered live beside the number while
// the slider is dragged, so unlike the hero phrases these are keyed to the
// value rather than rotated on a timer. Thresholds span the clamp range.
function scrollSpeedLabel(factor) {
  if (factor <= 0.2) return "Glacial"
  if (factor <= 0.4) return "Decaf"
  if (factor <= 0.6) return "Cruising"
  if (factor <= 1.0) return "Caffeinated"
  if (factor <= 1.5) return "Overclocked"
  return "Ludicrous"
}

// Clamp pointer sensitivity to Hyprland's [-1.0, 1.0] and round to 1 decimal.
// 0.0 is libinput's unaccelerated baseline, not a midpoint of "off" and "on".
function clampSensitivity(value) {
  var v = Number(value)
  if (!isFinite(v)) v = 0
  if (v < -1.0) v = -1.0
  if (v > 1.0) v = 1.0
  return Math.round(v * 10) / 10
}

// Label for pointer sensitivity. Centered on 0.0 = system default, so the
// scale reads outward in both directions rather than slow-to-fast.
function pointerSpeedLabel(sensitivity) {
  var v = clampSensitivity(sensitivity)
  if (v <= -0.7) return "Sedated"
  if (v <= -0.3) return "Unhurried"
  if (v < 0) return "Relaxed"
  if (v === 0) return "Stock"
  if (v < 0.4) return "Perky"
  if (v < 0.7) return "Twitchy"
  return "Caffeinated"
}

if (typeof module !== "undefined") {
  module.exports = {
    clampScrollFactor: clampScrollFactor,
    scrollSpeedLabel: scrollSpeedLabel,
    clampSensitivity: clampSensitivity,
    pointerSpeedLabel: pointerSpeedLabel
  }
}
