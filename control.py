#!/usr/bin/env python3
"""Read or set the TrackPoint pointer sensitivity.

  control.py          print {"value": <current>, "device": <name>}
  control.py <value>  set the sensitivity, from -1 (slower) to 1 (faster)

The value is stored and applied through trackpads.py, the single writer for
touchpad and TrackPoint settings, so both devices validate, reload and roll
back the same way.
"""
import json
import math
import sys

sys.dont_write_bytecode = True
import trackpads  # noqa: E402
import trackpoint  # noqa: E402


def main():
    device = trackpoint.detect_device()
    value = None
    if len(sys.argv) > 1:
        value = float(sys.argv[1])
        if not math.isfinite(value) or not -1 <= value <= 1:
            raise ValueError('Sensitivity must be between -1 and 1.')
        value = round(value, 2)
    with trackpads.session() as (state, live, previous):
        key = trackpads.device_key(state, device)
        if value is not None:
            state = trackpads.change(state, key, 'sensitivity', value)
        group = state['devices'][key]
        print(json.dumps({'value': float(group['settings']['sensitivity']), 'device': device}))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'error': str(exc)}))
        sys.exit(1)
