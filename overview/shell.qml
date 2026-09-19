import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland
import "Model.js" as Model

ShellRoot {
    id: root
    property var snapshot: ({workspaces: []})
    property var lifetimes: []
    property int serial: 0
    property int monitorId: -1
    property string monitorName: ""
    property int priorWorkspace: 0
    property int currentWorkspace: 0
    property var priorWindow: null
    property string currentActiveAddress: ""
    property var activation: null
    property color foreground: "#ded4b8"
    property color backgroundColor: "#293238"
    property color accent: "#80b9b2"
    property url wallpaperSource: ""

    function monitorGeometry(monitor) {
        const raw = monitor.lastIpcObject || {};
        const scale = typeof raw.scale === "number" && raw.scale > 0 ? raw.scale : NaN;
        const rotated = [1, 3, 5, 7].indexOf(raw.transform) >= 0;
        return {id: monitor.id, name: monitor.name, x: raw.x, y: raw.y,
            width: (rotated ? raw.height : raw.width) / scale,
            height: (rotated ? raw.width : raw.height) / scale};
    }

    function syncActiveToplevel() {
        let toplevel = Hyprland.activeToplevel;
        // The exclusive layer can temporarily clear activeToplevel. Preserve
        // the last compositor window until Hyprland reports its replacement.
        const valid = candidate => candidate && candidate.monitor && candidate.workspace
            && candidate.monitor.id === monitorId && candidate.workspace.id === currentWorkspace
            && (!candidate.lastIpcObject || (candidate.lastIpcObject.hidden !== true && candidate.lastIpcObject.mapped !== false));
        if (!valid(toplevel)) {
            const focused = Hyprland.toplevels.values.filter(candidate => valid(candidate)
                && candidate.lastIpcObject && candidate.lastIpcObject.focusHistoryID === 0);
            if (focused.length !== 1) return false;
            toplevel = focused[0];
        }
        const address = toplevel.address || "";
        if (address === currentActiveAddress) return false;
        currentActiveAddress = address;
        return true;
    }

    function rebuild() {
        if (!session.opened && !session.pending) return;
        root.syncActiveToplevel();
        const monitors = Hyprland.monitors.values;
        if (!monitors.some(m => m.id === monitorId)) { session.dismiss("monitor-removed"); return; }
        const live = Hyprland.toplevels.values;
        lifetimes = lifetimes.filter(record => live.indexOf(record.source) >= 0);
        const records = new Map(lifetimes.map(record => [record.source, record]));
        const windows = live.map(w => {
            let record = records.get(w);
            if (!record) { record = {source: w, token: String(++serial)}; lifetimes.push(record); }
            const raw = w.lastIpcObject || {};
            return {address: w.address, pid: raw.pid, token: record.token,
                workspace: {id: w.workspace ? w.workspace.id : 0},
                monitor: w.monitor ? w.monitor.id : null, hidden: raw.hidden, mapped: raw.mapped,
                title: w.title, class: raw.class, at: raw.at, size: raw.size};
        });
        const next = Model.buildSnapshot({session: session.sessionIdentity, monitorId: monitorId,
            monitors: monitors.map(root.monitorGeometry),
            workspaces: Hyprland.workspaces.values.map(w => ({id: w.id, name: w.name,
                monitorID: w.monitor ? w.monitor.id : null})), windows: windows,
            activeAddress: currentActiveAddress,
            activeWorkspaceId: currentWorkspace});
        // Preserve live cards and their paging when a compositor event leaves
        // the overview model unchanged. Titles refresh on the next open.
        if (JSON.stringify(next) !== JSON.stringify(snapshot)) snapshot = next;
    }
    function sourceFor(entry) {
        const record = lifetimes.find(r => r.token === entry.token);
        return record && record.source ? record.source.wayland : null;
    }
    function select(kind, key) {
        rebuild();
        if (!session.opened || session.lockState !== "unlocked") return;
        const entry = Model.resolveSelection(snapshot, {kind: kind, key: key});
        if (!entry) return;
        if (kind === "workspace") {
            const workspace = Hyprland.workspaces.values.find(w => w.id === entry.id && w.monitor && w.monitor.id === monitorId);
            if (workspace) {
                activation = null;
                session.dismiss("selection");
                workspace.activate();
            }
            return;
        }
        const record = lifetimes.find(r => r.token === entry.token);
        activation = {kind: kind, entry: entry, source: record ? record.source : null};
        session.dismiss("selection");
        activateDelay.restart();
    }
    function createWorkspace() {
        if (!session.opened || session.lockState !== "unlocked") return;
        const monitor = Hyprland.focusedMonitor;
        if (!monitor || monitor.id !== monitorId) return;
        const used = new Set(Hyprland.workspaces.values.map(w => w.id));
        let id = 1;
        while (used.has(id) && id < 2147483647) id++;
        if (used.has(id)) return;
        activation = null;
        session.dismiss("selection");
        // Only a generated integer enters the dispatch expression.
        Hyprland.dispatch('hl.dsp.focus({ workspace = "' + id + '" })');
    }
    Process {
        id: wallpaper
        running: true
        command: ["readlink", "-e", "--", (Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state") + "/omarchy/current/background"]
        onStarted: wallpaperDeadline.restart()
        stdout: StdioCollector { id: wallpaperPath; waitForEnd: true }
        onExited: code => {
            wallpaperDeadline.stop();
            const path = wallpaperPath.text.trim();
            root.wallpaperSource = code === 0 && path.startsWith("/")
                ? "file://" + path.split("/").map(encodeURIComponent).join("/") : "";
        }
    }
    Timer {
        id: wallpaperDeadline
        interval: 1000
        onTriggered: { root.wallpaperSource = ""; wallpaper.signal(9); }
    }
    Session {
        id: session
        onWillOpen: {
            if (!wallpaper.running) wallpaper.running = true;
            activateDelay.stop();
            root.activation = null;
            const monitor = Hyprland.focusedMonitor;
            if (!monitor || !Quickshell.screens.some(s => s.name === monitor.name)) {
                session.dismiss("no-monitor"); return;
            }
            root.monitorId = monitor.id;
            root.monitorName = monitor.name;
            root.priorWorkspace = Hyprland.focusedWorkspace ? Hyprland.focusedWorkspace.id : 0;
            root.currentWorkspace = root.priorWorkspace;
            root.priorWindow = Hyprland.activeToplevel;
            root.currentActiveAddress = root.priorWindow ? root.priorWindow.address : "";
            root.syncActiveToplevel();
            root.rebuild();
            Hyprland.refreshMonitors();
            Hyprland.refreshWorkspaces();
            Hyprland.refreshToplevels();
        }
        onClosed: reason => {
            refresh.stop();
            root.snapshot = {workspaces: []};
            if (["escape", "button", "closed"].indexOf(reason) >= 0) {
                root.activation = {kind: "restore", source: root.priorWindow};
                activateDelay.restart();
            } else if (reason !== "selection") root.activation = null;
            root.priorWindow = null;
        }
    }
    Timer {
        id: activateDelay
        interval: 50
        onTriggered: {
            const action = root.activation;
            root.activation = null;
            if (!action || session.opened || session.pending || session.lockState !== "unlocked") return;
            const monitor = Hyprland.monitors.values.find(m => m.id === root.monitorId);
            if (!monitor) return;
            const source = action.source;
            if (!source || Hyprland.toplevels.values.indexOf(source) < 0 || source.monitor !== monitor || !source.wayland) return;
            if (action.kind === "restore") {
                if (!Hyprland.focusedWorkspace || Hyprland.focusedWorkspace.id !== root.priorWorkspace
                    || !source.workspace || source.workspace.id !== root.priorWorkspace) return;
            } else {
                const raw = source.lastIpcObject || {};
                if (raw.hidden || raw.mapped === false || raw.pid !== action.entry.pid
                    || !source.workspace || source.workspace.id !== action.entry.workspaceId) return;
            }
            source.wayland.activate();
        }
    }
    Connections {
        target: Hyprland
        function onFocusedWorkspaceChanged() {
            if (!session.opened) return;
            const workspace = Hyprland.focusedWorkspace;
            if (!workspace || !workspace.monitor || workspace.monitor.id !== root.monitorId) {
                session.dismiss("workspace-changed"); return;
            }
            root.currentWorkspace = workspace.id;
            root.syncActiveToplevel();
            root.rebuild();
        }
        function onRawEvent(event) {
            if (!session.opened) return;
            if (/^(openwindow|closewindow|movewindow|workspace|createworkspace|destroyworkspace|monitor|changegroup|togglegroup)/.test(event.name))
                refresh.restart();
        }
    }
    Timer { id: refresh; interval: 100; onTriggered: root.rebuild() }
    FileView {
        path: (Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state") + "/omarchy/current/theme/shell.toml"
        watchChanges: true
        onFileChanged: reload()
        onLoaded: {
            const content = text();
            function color(key, fallback) {
                const match = content.match(new RegExp("^" + key + "\\s*=\\s*\"(#[0-9a-fA-F]{6})\"", "m"));
                return match ? match[1] : fallback;
            }
            root.foreground = color("text", "#ded4b8");
            root.backgroundColor = color("background", "#293238");
            root.accent = color("active-border", "#80b9b2");
        }
    }
    LazyLoader {
        active: true
        component: PanelWindow {
            id: panel
            readonly property string targetMonitor: root.monitorName || (Hyprland.focusedMonitor ? Hyprland.focusedMonitor.name : "")
            screen: Quickshell.screens.find(s => s.name === targetMonitor) || Quickshell.screens[0] || null
            visible: session.opened && session.lockState === "unlocked" && preparedWallpaper.presentable
            anchors { top: true; bottom: true; left: true; right: true }
            exclusionMode: ExclusionMode.Ignore
            color: root.backgroundColor
            WlrLayershell.namespace: "trackpad-plus-overview"
            WlrLayershell.layer: WlrLayer.Overlay
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
            PreparedWallpaper {
                id: preparedWallpaper
                // Screen dimensions are available before the layer is mapped.
                width: panel.screen ? panel.screen.width : 1
                height: panel.screen ? panel.screen.height : 1
                pixelRatio: panel.screen ? panel.screen.devicePixelRatio : 1
                source: root.wallpaperSource
                requested: session.opened && session.lockState === "unlocked"
                resolving: wallpaper.running
                fallbackColor: root.backgroundColor
            }
            Loader {
                anchors.fill: parent
                active: panel.visible
                sourceComponent: Overview {
                    id: overview
                    anchors.fill: parent
                    paintWallpaper: false
                    snapshot: root.snapshot
                    sourceFor: root.sourceFor
                    foreground: root.foreground
                    backgroundColor: root.backgroundColor
                    accent: root.accent
                    wallpaperSource: root.wallpaperSource
                    onInFlightChanged: session.captures = inFlight
                    onReadyCountChanged: { session.ready = readyCount; if (readyCount > 0 && session.mapped) session.rendered = true; }
                    onDismiss: session.dismiss("escape")
                    onSelected: (kind, key) => root.select(kind, key)
                    onCreateWorkspace: root.createWorkspace()
                    Component.onCompleted: forceActiveFocus()
                }
            }
            Connections {
                target: panel.contentItem.Window.window
                function onFrameSwapped() {
                    if (panel.visible) { session.mapped = true; session.rendered = session.ready > 0; session.result = session.rendered ? "rendered" : "opened"; }
                }
            }
        }
    }
}
