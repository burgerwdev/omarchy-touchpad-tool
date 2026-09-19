# Workspace overview feasibility probe

Experimental development tooling for the overview plan's U1 gate. This is not
an installed Trackpad Plus feature and must not be enabled for users as a release.
The M2 mechanism checks now pass. Production integration still requires its own
model, lifecycle, interaction, and release verification.

The probe runs separately from the bar and compositor. It captures only the two
accompanying fixture windows, checks real captured pixels in memory, and never
saves screenshots or records application titles. Synthetic images are not
substituted for Wayland capture. The fixture windows themselves contain a known
four-color pattern so orientation and nonempty content can be verified.

## Run the checks

Run from the repository root in an unlocked, active Omarchy graphical session.
Requires `qs`, Python 3, Qt Quick/QtTest, `hyprctl`, and `wtype`. The XWayland check
also requires the Qt XCB platform plugin. An existing inactive ordinary workspace
on the current monitor is required; the harness does not create one.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 tools/overview-probe/test_lock_watch.py
python3 tools/overview-probe/check.py
python3 tools/overview-probe/check.py --xwayland
python3 tools/overview-probe/check.py --cycles 100
/usr/lib/qt6/bin/qmllint tools/overview-probe/shell.qml tools/overview-probe/fixtures.qml
```

Live checks briefly create two windows, move one fixture to the existing inactive
workspace, and open/close the probe. They test fullscreen, Escape, source removal,
and forced process termination. They restore the prior focus if the user has not
changed workspaces and the session is still unlocked. No configuration files,
per-device settings, gesture registrations, plugin installation, or services are
changed. Core dumps are disabled for the test processes.

The fullscreen fixture waits for two normal frame presentations before readback,
then checks image dimensions against the window's fractional pixel ratio and
verifies all four quadrant colors. QtTest's synchronous `grabImage` can otherwise
render a resized scene into an old swapchain; waiting for compositor geometry
alone was insufficient. Using the screen's integer pixel ratio was also incorrect
on the M2's 1.6× display scale. The corrected check passes Wayland and XWayland.
A separate real foot application check confirms nonuniform preview content for
active, inactive-workspace, and fullscreen windows.

The capture checker maps coordinates into the probe's content item before
sampling. QtTest's `grabImage(item)` uses the item's local coordinates, which
otherwise samples the wrong area for nested items. No image is written to disk.

## Lock-state observer

`lock-watch.py` uses the compositor's `hyprland_lock_notifier_v1` protocol through
a small standard-library Wayland client. Two ordered sync roundtrips establish
initial state; the compositor then sends lock/unlock events. Missing protocol,
disconnect, malformed messages, or helper exit make the probe fail closed.
This reports completed lock transitions, not the beginning of a lock request.

```bash
python3 tools/overview-probe/lock-watch.py
```

The Quickshell process uses `--exit-on-consumer-close` so the observer exits when
its stdout reader disappears, including after the overview is killed while the
compositor is idle. It does not repeatedly invoke the bar or use logind's advisory
locked hint. The observer does not capture windows or unlock the session.

## Evidence from the M2 session

Observed on 2026-09-14 with Hyprland 0.56.2 (`efb50993780079460b0cbed1363e2166a2de1d9f`),
Quickshell 0.3.1, and Qt 6.11.2 on ARM64 Linux:

| Check | Evidence |
|---|---|
| Wayland and XWayland capture | Active and inactive-workspace fixtures passed actual pixel/orientation checks |
| Fullscreen | Wayland and XWayland pass after normal-presentation barriers, fractional size validation, and strict pixel checks |
| Workspace preservation | Capturing an inactive-workspace window did not activate its workspace |
| Escape and source removal | Explicit prior-window restoration fixes a reproduced focus mismatch; closing the source releases capture |
| Forced termination | SIGKILL released the overview surface and its observer exited; workspace and focus remained correct |
| Capture teardown | Hidden probe reported no capture source and no retained image |
| Initial lock state | Real compositor connection reported initial unlocked state through ordered sync |
| Observer error paths | 12 fake-server tests passed, including fragmented frames, initial locked/unlocked, transition events, timeouts, disconnects and consumer death |
| Live observer loss | Terminating the owned watcher cleared capture and closed the overlay; explicit reopening restarted observation and capture successfully |
| Physical gestures | User confirmed three-finger up opens and down dismisses while the overlay owns keyboard focus; repeated open/close events corroborate the report |
| Horizontal workspace swipes | User reported the local horizontal-swipe check worked; the native horizontal binding was left unchanged |
| Lock while visible | Real lock event closed the visible preview and cleared its capture; unlock left it closed, followed by a successful explicit reopen |
| Timing | One 100-cycle run measured 389 ms cold probe launch-to-frame; first 30 warm requests had 41.5 ms median and 49 ms p95 |
| Resource use | Same run: probe descriptors stayed at 46; RSS was 157,456 KiB initially and 147,712 KiB after 100 cycles, with no upward trend |

Timing is diagnostic evidence, not a release envelope. Cold timing includes probe
launch and IPC readiness, but there is no production gesture launcher yet. RSS is
the probe process, including test instrumentation, rather than total compositor,
GPU, and observer memory. QML lint currently reports dynamic QtTest object-member
and Quickshell PanelWindow metadata warnings; live loading succeeds.

The manual session used temporary runtime-only three-finger up/down callbacks,
removed at the end of the test. No configuration files were edited. Session
backups and state-only event records are under
`~/.local/state/omarchy/backups/trackpad-overview-live-*`. The recorded transition
on 2026-09-14 at 17:00:28 local time changed from a visible captured frame to
`lock-locked`, `opened=false`, `hasContent=false`, and `captureAttached=false`.
At 17:00:33, state changed to unlocked without reopening. These samples establish
teardown and no automatic reopen, not a bound on frame-by-frame lock latency.

After this manual session, the user reported audio stuck on mute. Both `wpctl`
and `pactl` hung despite the audio services reporting active. The speaker-protection
daemon recorded a suspend event at 17:00:30, within the lock test. WirePlumber
also failed to stop normally; terminating its hung process allowed the requested
user audio-service restart to complete. Queries then returned promptly, with the
existing protected speaker output unmuted at 40%. Speaker protection remained
running. The timing suggests a possible suspend/resume connection, but does not
establish whether the probe contributed. Actual playback confirmation and a
controlled reproduction remain pending. A subsequent controlled lock/unlock test
left both audio APIs responsive; the earlier hang did not reproduce.

## Follow-up integration checks

The explicit real-lock test now confirms that an open request is rejected while
locked, including a pending open that restarts its observer in the locked session.
Unlocking does not reopen or retain the image. The test checks audio responsiveness
before and after locking. It requires the user to unlock normally:

```bash
python3 tools/overview-probe/check_application.py
python3 tools/overview-probe/check_lock.py
```

Count callbacks against controlled physical swipes in the final integration;
functional repeated up/down checks passed. The prototype is not a full workspace
navigator. U2-U6 must still verify the complete model, launch protocol, selection,
provider persistence, failure states, and packaging. More applications and x86
hardware need coverage before extending compatibility claims.

## Cleanup and rollback

The harness uses `finally` cleanup for its owned processes. If the harness itself
is forcibly interrupted before cleanup, stop only these configurations:

```bash
qs kill -p "$PWD/tools/overview-probe/shell.qml"
qs kill --any-display -p "$PWD/tools/overview-probe/fixtures.qml"
```

No installed plugin or settings rollback is needed for these checks. The working
checkout and desktop state were backed up before development under
`~/.local/state/omarchy/backups/trackpad-overview-*`; recovery archives contain the
checkout (including Git history and ignored/untracked files) and pre-test desktop
state. Restore only specific files after comparing them with newer user changes.

## Protocol references

- [Hyprland lock notification protocol](https://github.com/hyprwm/hyprland-protocols/blob/main/protocols/hyprland-lock-notify-v1.xml)
- [Pinned compositor implementation](https://github.com/hyprwm/Hyprland/blob/efb50993780079460b0cbed1363e2166a2de1d9f/src/protocols/LockNotify.cpp)
- [Quickshell window capture](https://quickshell.org/docs/v0.3.1/types/Quickshell.Wayland/ScreencopyView/)
- [QtTest image checks](https://doc.qt.io/qt-6/qml-qttest-testcase.html#grabImage-method)
