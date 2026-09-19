#!/usr/bin/env python3
"""Lint all QML; allow only identified gaps in installed host API metadata."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

repo = Path(__file__).resolve().parent


def find_lint():
    """Prefer a qmllint that understands --json; /usr/bin/qmllint may be Qt5-era."""
    candidates = [shutil.which('qmllint'), '/usr/lib/qt6/bin/qmllint']
    for candidate in candidates:
        if not candidate or not Path(candidate).exists():
            continue
        probe = subprocess.run([candidate, '--help'], capture_output=True, text=True)
        if '--json' in probe.stdout:
            return candidate
    raise SystemExit('No qmllint with --json support found (tried PATH and /usr/lib/qt6/bin/qmllint)')


lint = find_lint()
sources = sorted([*repo.glob('*.qml'), *(repo / 'overview').rglob('*.qml')])
with tempfile.TemporaryDirectory(prefix='trackpad-plus-lint-') as directory:
    (Path(directory) / 'qs').symlink_to('/usr/share/omarchy/shell', target_is_directory=True)
    result = subprocess.run([lint, '-I', directory, '--json', '-',
                             *map(str, sources)],
                            capture_output=True, text=True, timeout=30)
    if not result.stdout:
        raise SystemExit(result.stderr or 'qmllint produced no results')
    report = json.loads(result.stdout)
    failures = []
    known = 0
    for source in report['files']:
        for warning in source.get('warnings', []):
            if warning['type'] == 'info':
                continue
            message = warning['message']
            host_property = warning['id'] == 'missing-property' and re.fullmatch(
                r'Member "(foreground|fontFamily|iconFont|body|caption|controlGap|display|heading|rowPaddingX|title)" not found on type "QObject"', message)
            host_signal = warning['id'] == 'signal-handler-parameters' and message == (
                'Type QProcess::ExitStatus of parameter exitStatus in signal called exited was not found, '
                'but is required to compile onExited. Did you add all imports and dependencies?')
            relative = Path(source['filename']).relative_to(repo).as_posix()
            panel = relative in ('Panel.qml', 'TrackpadPanel.qml', 'TrackPointPanel.qml')
            allowed = (panel and (host_property or host_signal)) or (
                relative in ('overview/Session.qml', 'overview/shell.qml') and host_signal)
            if warning['type'] == 'warning' and allowed:
                known += 1
            else:
                failures.append(f"{source['filename']}:{warning['line']}: {message}")
    if failures:
        raise SystemExit('\n'.join(failures))
    if result.returncode:
        raise SystemExit(result.stderr or f'qmllint exited {result.returncode}')
    print(f"qmllint passed for {len(report['files'])} QML sources; {known} known host metadata diagnostics (dynamic bar/style properties, QProcess::ExitStatus).")
