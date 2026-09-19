# Release safety review

Reviewed on 2026-09-13, starting from `a95581a` (2.0.3). The fixes accompany
this document on `fix/release-safety-review`. This is a source review and
regression test pass, not an independent security certification.

## Findings addressed

| Area | Finding | Change |
| --- | --- | --- |
| First installation | Reading state generated device overrides from global defaults; a later reload could replace existing per-device customization without an edit. | Newly discovered devices produce no overrides until their first edit. Previously saved settings retain their behavior. |
| Interrupted edits | A terminated helper could leave live settings changed while both saved files still matched the previous state. | Write a recovery journal before applying; restore its snapshot on the next read. |
| Failed updates | A rejected or partially applied compositor request was outside the rollback handler. A failed disk rollback could also prevent live rollback. | Attempt rollback for apply errors, attempt disk and live restoration independently, preserve the original error, and retain the journal when recovery cannot finish. |
| State files | Reads followed symlinks and could block on FIFOs; parent directories were not pinned during writes. | Use descriptor-relative, no-follow operations, regular-file/ownership/link checks, bounded reads, private temporary files, and file/directory synchronization. |
| Compatibility | A future state version was silently rewritten as version 3. Malformed commands could cause initialization or migration before rejection. | Reject unsupported schemas and invalid commands before changing settings. Validate the complete migrated state, device names, settings, and undo records. |
| Resource use | Compositor output and direct CLI lock waits were unbounded. Repeated UI actions could grow the queue. | Cap responses at 1 MiB, requests at four seconds, lock acquisition at two seconds, and pending actions at 128. Combine consecutive scalar changes. |
| UI correctness | Encoded spaces broke backend paths, removed devices and undo records could remain stale, and a failed save could still display “Applied.” | Decode local paths, clear stale state, and display errors in the curve editor. |
| Curve rendering | Each of 161 plotted positions regenerated all 43 native samples. | Generate samples once per paint and reuse them without changing the plotted response. |
| Test artifacts | The QML test wrote a screenshot to a predictable shared temporary path. | Remove the unnecessary file write while keeping the rendering assertion. |

## Validation

- Python backend: 29 tests, including injection rejection, Apple grouping,
  device isolation, curve/undo migration, native libinput acceptance, and
  JS/Python sample equivalence.
- Filesystem failure tests: symlinks, parent symlinks, FIFOs, hard links,
  oversized input, private file permissions, failures at either persistence
  file, persistent disk failure, and failed rollback.
- Crash recovery tests: matching old JSON/Lua with a pending live edit, a crash
  after both files were written, and termination of an actual helper process
  after its fake compositor received an edit.
- Repeated file operations and native validation: 100 iterations with no
  increase in open file descriptors. Native configuration objects are destroyed
  in `finally`; subprocesses are killed and reaped on request failure.
- Installation: 11 tests against a fake compositor and temporary state,
  including first-run isolation, future-version preservation, process deadlines,
  excessive output, persistence, and recovery. The plugin path contains spaces.
- Node: actual panel functions exercised for callback ordering, stale reads,
  device selection, undo, queue limits, timeouts, and cached curve equivalence.
- IPC: all five commands against the installed Omarchy base Panel in a separate
  offscreen Quickshell instance.
- Qt: 11 passing entries, including initialization/cleanup, covering the real
  curve editor's keyboard, mouse, spinners, Apply, undo, bounds, and error status.
- `qmllint`: all three QML files pass the repository checker. It explicitly
  permits 76 existing diagnostics for missing Omarchy/Quickshell host metadata;
  the editor and its test have no warnings.
- Legacy Perl and Bash syntax, Git whitespace checks, and manifest inspection.
- Read-only host checks: current saved state passes validation without
  migration, generated Lua matches, actual custom curves pass native libinput
  validation, and one connected Apple group is discovered. Settings file hashes
  remain unchanged; no Hyprland config errors or failed system/user services.

## Privacy and trust boundaries

The current plugin runtime contains no telemetry, HTTP requests, credential
access, root commands, or package installation. It reads compositor device/options
data and its state, writes its own state and generated per-device Lua, and invokes
`hyprctl`. Failed first edits can require a config-only reload to remove their
runtime override. Generated Lua contains validated literals, without file reads
or execution of user-supplied code. The inherited helpers were also reviewed;
the current panel does not invoke them.

Common private-key and access-token patterns were absent from current tracked
source and reachable Git history. The shipped images were visually inspected.
Pattern scanning cannot identify every possible secret. This review also does
not prove the absence of every native-memory leak or defect in dependencies.

The plugin runs with the desktop user's permissions, not in a security sandbox.
These file checks prevent unsafe path handling; they cannot protect a session
already controlled by another process with the same user privileges.

## Compatibility limits and remaining release checks

- The updated branch has not been installed into the active desktop during this
  review. Before publishing these fixes, perform the development guide's live
  Apply/Restore, shell-restart, and Hyprland-reload checks with a settings backup.
- Automated compositor tests use fixtures. Physical testing here covers one
  built-in Apple trackpad; other hardware still needs hands-on coverage.
- First edits apply all values shown for the selected group, initially based on
  global defaults and recognized legacy sensitivity rules. Arbitrary existing
  per-device settings are not imported. All Apple interfaces share one group.
- Hyprland window rules and application behavior can override scrolling. The
  plugin does not rewrite those rules. New interfaces in an already configured
  group receive persisted rules on reload or the next explicit group edit.
- Saving two files and applying compositor state is not a single transaction.
  Recovery needs writable storage and a working compositor. A crash can discard
  the most recent unconfirmed edit. Sudden power loss and failing physical
  storage were not tested; process termination and write failures were simulated.
- Symlinked state directories and shared writable state files now fail closed.
  Use real, privately writable directories and an absolute `XDG_STATE_HOME`.
  If relocating state, ensure Omarchy loads the corresponding generated Lua.
- Tested host dependencies: Hyprland 0.56.2, libinput 1.31.3, Qt 6.11.2.
  The plugin requires Lua-based Hyprland configuration and native custom-profile
  support. A successful API response cannot prove every hardware option took
  effect on every supported device.

Original Git history and both MIT copyright notices remain intact.
