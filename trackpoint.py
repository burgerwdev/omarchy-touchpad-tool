#!/usr/bin/env python3
"""Find the TrackPoint devices Hyprland reports.

Detection only: device settings are written through trackpads.py, which owns
the per-device state JSON and the generated Lua rules, so the TrackPoint and
the touchpad share one validate/reload/rollback path.
"""
import json
import subprocess


def trackpoint_names(mice):
    """Every TrackPoint-style device name in a `hyprctl devices -j` mouse list."""
    return [mouse.get('name', '') for mouse in mice if 'trackpoint' in mouse.get('name', '').lower()]


def detect_device(mice=None):
    if mice is None:
        out = subprocess.run(['hyprctl', 'devices', '-j'], capture_output=True, text=True, check=True).stdout
        mice = json.loads(out).get('mice', [])
    matches = trackpoint_names(mice)
    if not matches:
        raise RuntimeError('No TrackPoint found. This widget needs a ThinkPad-style TrackPoint.')
    return matches[0]
