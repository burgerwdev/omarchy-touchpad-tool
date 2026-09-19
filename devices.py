#!/usr/bin/env python3
"""Report the attached trackpads and TrackPoints.

One shared detector for the panel and for both device backends: touchpads come
from trackpads.group_devices and TrackPoints from hypr_input.trackpoint_names,
so a device can never be classified one way in the UI and another way in a
settings write. The tab list is decided here too, so "which tabs does this
machine have" has exactly one answer.

  devices.py   print {"touchpads": [...], "trackpoints": [...], "tabs": [...], "default_tab": ...}
"""
import json
import sys

sys.dont_write_bytecode = True
import hypr_input  # noqa: E402
import trackpads  # noqa: E402


def detect(mice):
    """Classify a `hyprctl devices -j` mouse list into the two device kinds."""
    groups = trackpads.group_devices(mice)
    touchpads = sorted({name for group in groups.values() for name in group['names']})
    trackpoints = sorted(hypr_input.trackpoint_names(mice))
    tabs = [kind for kind, present in (('trackpad', touchpads), ('trackpoint', trackpoints)) if present]
    return {
        'touchpads': touchpads,
        'trackpoints': trackpoints,
        'tabs': tabs,
        # The panel opens on the touchpad when there is one, else the TrackPoint.
        'default_tab': tabs[0] if tabs else '',
    }


def report():
    """Print one JSON line for the panel and return the exit status; never raises."""
    try:
        print(json.dumps(detect(json.loads(trackpads.hypr('devices', '-j'))['mice'])))
        return 0
    except Exception as exc:
        print(json.dumps({'error': str(exc)}))
        return 1


if __name__ == '__main__':
    sys.exit(report())
