#!/usr/bin/env python3
"""Report the attached touchpads and TrackPoints.

One shared detector for the panel and for the writer: the device lists come
from trackpads.group_all, the same grouping that decides which devices can be
configured, so a device can never be classified one way in the UI and another
way in a settings write. The tab list is decided here too, so "which tabs does
this machine have" has exactly one answer.

  devices.py   print {"touchpads": [...], "trackpoints": [...], "tabs": [...], "default_tab": ...}
"""
import json
import sys

sys.dont_write_bytecode = True
import trackpads  # noqa: E402


def detect(mice):
    """Classify a `hyprctl devices -j` mouse list into the two device kinds."""
    names = {'trackpad': [], 'trackpoint': []}
    for group in trackpads.group_all(mice).values():
        names[group['kind']].extend(group['names'])
    touchpads = sorted(set(names['trackpad']))
    trackpoints = sorted(set(names['trackpoint']))
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
