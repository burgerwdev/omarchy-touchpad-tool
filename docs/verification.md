# Verification record — merged Touchpad Tool

Environment: Omarchy 4.0 / Quattro shell, plugin `local.touchpad-tool` linked at
`~/.config/omarchy/plugins/local.touchpad-tool`. Devices on this machine:
`synaptics-tm3381-002` (touchpad) and `tpps/2-elan-trackpoint` (TrackPoint).

## (a) Test suites

| Suite | Result |
|---|---|
| `python3 test_trackpads.py` | 48 passed |
| `python3 test_trackpoints.py` | 11 passed (incl. both live-run regressions) |
| `python3 test_middle.py` | 7 passed |
| `python3 test_adopt.py` | 8 passed |
| `python3 test_devices.py` | 8 passed |
| `python3 test_install.py` | 19 passed |
| `python3 test_gestures.py` | 49 passed |
| `python3 test_overview_control.py` | 23 passed |
| `python3 test_overview_ipc.py` | 2 passed |
| `python3 test_ipc.py` | all five IPC commands verified |
| `node test-devicetabs.js` | 6 passed |
| `node test-selection.js` | passed |
| `node test-overview-model.js` | passed |
| `qmltestrunner tst_curve.qml` | 12 passed, 0 failed |
| `qmltestrunner tst_gestures.qml` | 13 passed, 0 failed |
| `qmltestrunner tst_overview.qml` | 18 passed, 0 failed |

## (b) QML lint

`python3 lint-qml.py` → `qmllint passed for 14 QML sources; 82 known host
metadata diagnostics` (dynamic bar/style properties and `QProcess::ExitStatus`
only). No unrelated warnings.

## (c) Install and panel

- `omarchy plugin validate .` → exit 0.
- `omarchy plugin list --json` → `local.touchpad-tool`, kind `bar-widget`, enabled.
- Opening the panel resolves the IPC target (`qs ipc call local.touchpad-tool
  open`; a bogus target reports `Target not found`) and creates the
  `omarchy-keyboard-panel` layer surface (1366×768) with no QML errors logged.

## (d) Controls driven against the live compositor

| Control | Evidence |
|---|---|
| Touchpad pointer/scroll/tap | `trackpads.py state` and `set` wrote only `settings.json` + `zz-local-touchpads.lua`; `hyprctl configerrors` empty; rules carry `sensitivity = 0.35`, `scroll_factor = 0.4`, `natural_scroll = true`, `tap_to_click = true` |
| TrackPoint sensitivity | `control.py` read `0.35`, wrote `0.25` → rule `hl.device({ name = "tpps/2-elan-trackpoint", sensitivity = 0.25 })`, read back `0.25`; restored afterwards |
| Middle button | `middle.py enable` wrote the marked binds block (press/release and `SUPER + mouse:274`) and set `scroll_method = "no_scroll"` through the same writer; `disable` removed the block and the setting, leaving `bindings.lua` byte-identical to the pre-test copy |
| Gestures | `gestures.py state` and `overview-status` return valid JSON; the overview companion path resolves inside the merged plugin directory. Applying live is refused here by design (`Gestures also exist in another Hyprland file; manage them there to avoid conflicts`) and `input.lua` was byte-identical afterwards, so the panel shows that state instead of writing |
| Bar icon | `omarchy bar set local.touchpad-tool logo dot|wordmark` updates the widget entry in `shell.json` |
| Config validity | `hyprctl configerrors` empty after every write above; `~/.config/hypr/input.lua` byte-identical (md5 `45ffc437279d411db2540cf803d73bf9`) throughout — no device settings are written there |

Rollback: unit tests cover live-apply failure and recovery
(`test_apply_failure_attempts_live_rollback_and_preserves_original_error`,
`test_failed_rollback_keeps_journal_for_next_process`); out-of-range and invalid
enum values are refused before anything is written.

## (e) Greps

- `hl.device(` appears in exactly one module: `trackpads.py`.
- One reload+validation helper (`trackpads.reload_checked`) is used by the device
  writer, `gestures.py` and `middle.py`. `gestures.py`'s remaining
  `configerrors` read is a read-only pre-flight check.
- Retired ids survive only in `adopt.py`'s legacy-marker table (the migration
  input) and in the upstream copies under `docs/upstream/`; no code writes to
  `~/.config/hypr/input.lua` for device settings.
- No `remove` call exists: `adopt.py` only runs `omarchy plugin disable`, and the
  removal command is text shown to the user.

## (f) Success criteria

1. Single installable plugin `local.touchpad-tool` (schemaVersion 1,
   `allowMultiple: false`), one bar icon and one panel — verified by manifest
   validation and plugin listing.
2. Both devices detected; `devices.py` returns
   `tabs: ["trackpad", "trackpoint"]`. Touchpad-only, TrackPoint-only and
   no-device lists are covered by `test_devices.py` and `test-devicetabs.js`
   (the unsupported tab is hidden).
3. Trackpad tab keeps Pointer (curve editor)/Scrolling/Gestures (gesture editor,
   overview provider); TrackPoint tab keeps the sensitivity slider, middle-button
   actions with per-app profiles and the bar-icon choice.
4. One write path (state JSON + generated Lua), one validate/reload/rollback
   path, one code path for sensitivity/scroll/tap shared by both devices.
5. Other plugins and legacy blocks are detected; actions are Back up, Back up &
   disable, Back up & import — each backs up first and runs only on a press.
   Disabling `davefano.trackpad-plus` was performed live with a backup first;
   removal remains an instruction for the user.
6. Suites, lint and QML tests pass; every control was driven and verified as in
   (d).

## Residual risk

The tab visuals were captured
(`assets/screenshots/trackpad-tab.png`, `trackpoint-tab.png`) but the agent
could not view images in this session, so "style matches the original panels" is
supported only by the fact that the tab bodies are the upstream QML files with
their own styling, plus a clean lint and a rendering panel. A human glance at
the panel is still the final check.
