"""Find the TrackPoint and edit its Hyprland device settings in input.lua.

An existing hl.device block for the TrackPoint is edited in place, so the
user's own settings stay where they wrote them. Without one, a marked block
is added at the end of input.lua and removed again once it holds nothing but
the device name. Every change is checked with hyprctl configerrors and put
back if Hyprland reports a problem.
"""
import json
from pathlib import Path
import re
import subprocess

CONFIG = Path.home() / '.config/hypr/input.lua'
BEGIN = '-- BEGIN io.github.artmoreno.trackpoint device (managed by the TrackPoint bar widget)'
END = '-- END io.github.artmoreno.trackpoint device'
MANAGED = re.compile(r'\n*' + re.escape(BEGIN) + r'\n.*?' + re.escape(END) + r'\n?', re.S)
DEVICE_BLOCK = re.compile(r'hl\.device\s*\(\s*\{(?P<body>.*?)\}\s*\)', re.S)
VALUE = r'("(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?|true|false)'


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


def _read():
    try:
        return CONFIG.read_text()
    except FileNotFoundError:
        raise RuntimeError(f'{CONFIG} not found.') from None


def _blocks(text, device):
    found = []
    for match in DEVICE_BLOCK.finditer(text):
        line_start = text.rfind('\n', 0, match.start()) + 1
        # Skip commented-out examples
        if '--' in text[line_start:match.start()]:
            continue
        name = re.search(r'(?<![\w.])name\s*=\s*"((?:[^"\\]|\\.)*)"', match['body'])
        if name and name[1] == device:
            found.append(match)
    if len(found) > 1:
        raise RuntimeError(f'Found {len(found)} hl.device blocks for {device} in input.lua; expected one.')
    return found[0] if found else None


def _field(key):
    return re.compile(r'(?<![\w.])' + re.escape(key) + r'\s*=\s*' + VALUE)


def _parse(raw):
    if raw.startswith('"'):
        return json.loads(raw)
    if raw in ('true', 'false'):
        return raw == 'true'
    return float(raw)


def get_value(device, key):
    """Return the configured value for key, or None when it isn't set."""
    block = _blocks(_read(), device)
    if block is None:
        return None
    field = _field(key).search(block['body'])
    return _parse(field[1]) if field else None


def _edit_body(body, key, literal):
    field = _field(key)
    if literal is None:
        return re.sub(r'\n?[ \t]*' + field.pattern + r'[ \t]*,?', '', body, count=1)
    if field.search(body):
        return field.sub(lambda m: f'{key} = {literal}', body, count=1)
    stripped = body.rstrip()
    separator = '' if not stripped.strip() or stripped.endswith(',') else ','
    if '\n' in body:
        indent = re.search(r'\n([ \t]*)\S', body)
        return f'{stripped}{separator}\n{indent[1] if indent else "  "}{key} = {literal},\n'
    return f'{stripped}{separator} {key} = {literal} '


def set_values(device, values):
    """Set each key to a Lua literal, or remove it when the literal is None."""
    original = _read()
    text = original
    for key, literal in values.items():
        block = _blocks(text, device)
        if block is None:
            if literal is None:
                continue
            text = (text.rstrip('\n') + f'\n\n{BEGIN}\nhl.device({{\n  name = {json.dumps(device)},\n'
                    f'  {key} = {literal},\n}})\n{END}\n')
            continue
        body = _edit_body(block['body'], key, literal)
        text = text[:block.start('body')] + body + text[block.end('body'):]

    # Drop the plugin's own block once only the device name is left in it
    managed = MANAGED.search(text)
    if managed:
        block = _blocks(managed[0], device)
        fields = re.findall(r'(?<![\w.])(\w+)\s*=', block['body']) if block else []
        if set(fields) <= {'name'}:
            text = text[:managed.start()] + '\n' + text[managed.end():]
            text = text.rstrip('\n') + '\n'

    if text != original:
        _write_checked(text, original)


def _write_checked(text, original):
    CONFIG.write_text(text)
    try:
        subprocess.run(['hyprctl', 'reload', 'config-only'], capture_output=True, text=True, check=True)
        errors = subprocess.run(['hyprctl', 'configerrors'], capture_output=True, text=True, check=True).stdout.strip()
        if errors:
            raise RuntimeError(errors)
    except Exception:
        # Hyprland keeps running on a broken config, so put the file back.
        CONFIG.write_text(original)
        subprocess.run(['hyprctl', 'reload', 'config-only'], capture_output=True, text=True)
        raise
