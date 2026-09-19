# TrackPoint for Omarchy

A ThinkPad TrackPoint widget for the Omarchy bar: a pointer sensitivity slider
and a programmable middle button.

![TrackPoint widget](screenshot-panel.png)

![ThinkPad wordmark in the bar](screenshot-wordmark.png)

![Bar icon options](screenshot-icons.png)

## Features

- **Sensitivity slider.** Drag and release to set the TrackPoint pointer
  sensitivity from -1 (slower) to 1 (faster). Arrow keys adjust it while the
  panel is focused. Applied instantly and kept for the next login.
- **Middle button actions** (opt-in). Run a command on:
  - a tap, double tap or triple tap
  - a hold, double tap + hold or triple tap + hold
  - a hold + flick up, down, left or right
  - a modifier + tap (Super, Alt, Shift, Ctrl and combinations)
- **Per-app profiles.** Override single actions while a specific app is
  focused, or block the default with "Do nothing".
- Presets for stock Omarchy commands (menus, screenshots, media, lock screen,
  nightlight, notifications and more), or any custom shell command.
- **Choice of bar icon.** The red *ThinkPad* wordmark, a red TrackPoint dot,
  or the color ThinkPad logo. Pick one under *Bar icon* in the panel, or run:

  ```sh
  omarchy bar set io.github.artmoreno.trackpoint logo wordmark   # or: dot, color
  ```

## Requirements

- Omarchy with the Quattro shell (plugin manifest `schemaVersion` 1)
- A ThinkPad-style TrackPoint that Hyprland lists with `trackpoint` in its
  name (check with `hyprctl devices`)
- `python3` (preinstalled on Omarchy)

## Install

```sh
omarchy plugin add https://github.com/ArtMoreno/omarchy-trackpoint.git --enable
```

The ThinkPad wordmark appears in the bar. Click it to open the panel.

## What it changes on your system

The widget only edits your Hyprland config when you use its controls, and it
checks every change with `hyprctl configerrors`, putting the file back if
Hyprland reports a problem.

| When | File | Change |
|---|---|---|
| You move the sensitivity slider | `~/.config/hypr/input.lua` | Sets `sensitivity` in your existing `hl.device` block for the TrackPoint. If you have none, adds a block marked `-- BEGIN io.github.artmoreno.trackpoint device`, removed again when you reset to default. |
| You press **Enable middle button actions** | `~/.config/hypr/input.lua` | Sets the TrackPoint's `scroll_method` to `"no_scroll"` so a hold isn't taken as hold-to-scroll. Your previous value is saved. |
| You enable actions and assign them | `~/.config/hypr/bindings.lua` | Adds a block marked `-- BEGIN io.github.artmoreno.trackpoint middle button` with binds for the actions you use. |
| You press **Turn off** | both files | Removes the bind block and restores your previous scroll setting. |

Middle button settings are stored in
`~/.local/state/omarchy/trackpoint/middle.json`, outside the plugin folder, so
updates keep them.

## Remove

1. Open the panel and press **Turn off** next to *Middle button* (if you
   enabled it). This restores scrolling and removes the bind block.
2. Press **Reset to default** if you want Hyprland's default sensitivity back.
3. Remove the plugin:

   ```sh
   omarchy plugin remove io.github.artmoreno.trackpoint
   ```

4. Optionally delete the saved middle button settings:

   ```sh
   rm -rf ~/.local/state/omarchy/trackpoint
   ```

If you removed the plugin without step 1, delete the block between
`-- BEGIN io.github.artmoreno.trackpoint middle button` and its `-- END` line in
`~/.config/hypr/bindings.lua`, and remove `scroll_method = "no_scroll"` from the
TrackPoint block in `~/.config/hypr/input.lua`, then run `hyprctl reload`.

## Notes

- Actions run your commands with your user's shell. Custom commands are
  yours to review.
- No network access, no elevated privileges, no background services.

## License

[MIT](LICENSE)
