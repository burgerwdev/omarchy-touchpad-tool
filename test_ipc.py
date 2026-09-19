"""Optional Omarchy integration check: real inherited IPC, isolated offscreen shell.

Requires the installed Omarchy UI modules, qs, and permission to bind a local
Unix socket. Does not load the plugin backend or modify desktop settings.
"""
from pathlib import Path
import json,os,re,shutil,subprocess,tempfile,time
repo=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix='trackpad-ipc-') as directory:
    root=Path(directory)
    for original, dest in [('Panel.qml','BasePanel.qml'),('PanelController.qml','PanelController.qml')]:
        shutil.copy2(Path('/usr/share/omarchy/shell/Ui')/original, root/dest)
    shutil.copytree('/usr/share/omarchy/shell/Commons',root/'Commons')
    props='\n'.join(re.findall(r'^  (?:moduleName|ipcTarget|manageIpc): .+$',(repo/'Panel.qml').read_text(),re.M))
    # Read the target from the panel so the check cannot drift from the manifest.
    target=re.search(r'^  ipcTarget: "(.+)"$',(repo/'Panel.qml').read_text(),re.M).group(1)
    (root/'shell.qml').write_text('''import QtQuick
import Quickshell
import Quickshell.Io
ShellRoot {
  BasePanel {
    id: panel
'''+props+'''
  }
  IpcHandler {
    target: "verification"
    function opened(): bool { return panel.opened }
  }
}
''')
    (root/'runtime').mkdir(mode=0o700)
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_QPA_PLATFORMTHEME='basic',QT_QUICK_CONTROLS_STYLE='Basic',XDG_RUNTIME_DIR=str(root/'runtime'))
    with (root/'qs.log').open('w+') as log:
        server=subprocess.Popen(['qs','-p',str(root),'--no-color'],env=env,stdout=log,stderr=log)
        def ipc(target,method):
            return subprocess.run(['qs','ipc','-p',str(root),'call','--',target,method],env=env,text=True,capture_output=True,timeout=3)
        try:
            for attempt in range(30):
                p=ipc('verification','opened')
                if p.returncode==0:break
                if server.poll() is not None:
                    log.seek(0);raise RuntimeError(log.read())
                time.sleep(0.1)
            else: raise RuntimeError('IPC harness did not start')
            assert p.stdout.strip()=='false',p.stdout
            for method,expected in [('open','true'),('close','false'),('toggle','true'),('hide','false'),('show','true')]:
                p=ipc(target,method)
                assert p.returncode==0,p.stderr
                observed=ipc('verification','opened')
                if observed.stdout.strip()!=expected:
                    log.flush();log.seek(0);print(log.read())
                    raise AssertionError(method)
            print(f'All five {target} IPC commands verified with the installed Omarchy base Panel in an isolated offscreen Quickshell instance.')
        finally:
            server.terminate()
            try:server.wait(timeout=3)
            except subprocess.TimeoutExpired:server.kill();server.wait()
