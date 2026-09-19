#!/usr/bin/env python3
"""Read or set the TrackPoint pointer sensitivity.

  control.py          print {"value": <current>, "device": <name>}
  control.py <value>  set the sensitivity, from -1 (slower) to 1 (faster)
"""
import json
import math
import sys

sys.dont_write_bytecode = True
import hypr_input  # noqa: E402

try:
    device = hypr_input.detect_device()
    if len(sys.argv) > 1:
        value = float(sys.argv[1])
        if not math.isfinite(value) or not -1 <= value <= 1:
            raise ValueError('Sensitivity must be between -1 and 1.')
        value = round(value, 2)
        # 0 is Hyprland's default, so clear the setting rather than pin it
        hypr_input.set_values(device, {'sensitivity': None if value == 0 else f'{value:.2f}'})
    else:
        current = hypr_input.get_value(device, 'sensitivity')
        value = float(current) if current is not None else 0.0
    print(json.dumps({'value': value, 'device': device}))
except Exception as exc:
    print(json.dumps({'error': str(exc)}))
    sys.exit(1)
