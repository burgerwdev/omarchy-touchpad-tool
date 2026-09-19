#!/usr/bin/env python3
"""Report the attached trackpads and TrackPoints.

One shared detector for the panel and for both device backends: touchpads come
from trackpads.group_devices and TrackPoints from hypr_input.trackpoint_names,
so a device can never be classified one way in the UI and another way in a
settings write.

  devices.py   print {"touchpads": [...], "trackpoints": [...]}
"""
import json
import sys

sys.dont_write_bytecode = True
import hypr_input  # noqa: E402
import trackpads  # noqa: E402


def detect(mice):
    """Classify a `hyprctl devices -j` mouse list into the two device kinds."""
    groups = trackpads.group_devices(mice)
    return {
        'touchpads': sorted({name for group in groups.values() for name in group['names']}),
        'trackpoints': sorted(hypr_input.trackpoint_names(mice)),
    }


def main():
    print(json.dumps(detect(json.loads(trackpads.hypr('devices', '-j'))['mice'])))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'error': str(exc)}))
        sys.exit(1)
