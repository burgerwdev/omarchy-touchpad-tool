import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland
import QtTest

// Disposable feasibility probe. Only captures its accompanying fixture windows.
ShellRoot {
    id: root
    property bool opened: false
    property bool pending: false
    property string lockState: "unknown"
    property string result: "idle"
    property string requestedAddress: ""
    property var captureTarget: null
    property double startedAt: 0
    property double latencyMs: -1
    property int openCount: 0
    property int closeCount: 0
    property string pixelCheck: "not-checked"
    property var priorWindow: null
    property int priorWorkspace: -1

    function closeProbe(reason) {
        pending = false;
        opened = false;
        captureTarget = null;
        result = reason;
        closeCount++;
        captureDeadline.stop();
        autoClose.stop();
        if (["escape", "button", "ipc-close", "auto-closed"].indexOf(reason) >= 0)
            restoreFocus.restart();
    }

    function finishOpen() {
        if (!pending || lockState !== "unlocked") return;
        const targets = Hyprland.toplevels.values;
        for (let i = 0; i < targets.length; i++) {
            const target = targets[i];
            if (target.address.replace(/^0x/, "") !== requestedAddress) continue;
            // Never fall back to another window or disclose window metadata.
            if (target.title !== "Trackpad Plus probe A" && target.title !== "Trackpad Plus probe B") break;
            if (!target.wayland) break;
            pending = false;
            opened = true;
            captureTarget = target.wayland;
            result = "capturing";
            openCount++;
            captureDeadline.restart();
            autoClose.restart();
            return;
        }
        closeProbe("fixture-unavailable");
    }

    function requestOpen(address) {
        if (!/^(0x)?[0-9a-fA-F]+$/.test(address)) return "invalid-address";
        restoreFocus.stop();
        if (!opened) {
            priorWindow = Hyprland.activeToplevel;
            priorWorkspace = Hyprland.focusedWorkspace ? Hyprland.focusedWorkspace.id : -1;
        }
        closeProbe("checking-lock");
        requestedAddress = address.replace(/^0x/, "");
        startedAt = Date.now();
        latencyMs = -1;
        pending = true;
        if (!lockCheck.running) {
            lockState = "unknown";
            lockCheck.running = true;
        } else if (lockState === "unlocked") finishOpen();
        else if (lockState === "locked") closeProbe("lock-locked");
        return "pending";
    }

    Timer {
        id: restoreFocus
        interval: 50
        onTriggered: {
            if (root.opened || root.lockState !== "unlocked" || !root.priorWindow
                || !Hyprland.focusedWorkspace || Hyprland.focusedWorkspace.id !== root.priorWorkspace
                || Hyprland.toplevels.values.indexOf(root.priorWindow) < 0) return;
            const address = root.priorWindow.address.replace(/^0x/, "");
            if (!/^[0-9a-fA-F]+$/.test(address)) return;
            if (!root.priorWindow.workspace || root.priorWindow.workspace.id !== root.priorWorkspace) return;
            focusProcess.command = ["hyprctl", "eval", 'hl.dispatch(hl.dsp.focus({window="address:0x' + address + '"}))'];
            focusProcess.running = true;
        }
    }
    Process {
        id: focusProcess
        stdout: StdioCollector {}
        stderr: StdioCollector {}
        onStarted: focusDeadline.restart()
        onExited: focusDeadline.stop()
    }
    Timer { id: focusDeadline; interval: 2000; onTriggered: focusProcess.signal(9) }

    Process {
        id: lockCheck
        command: ["python3", Quickshell.shellPath("lock-watch.py"), "--format", "plain", "--exit-on-consumer-close"]
        running: true
        onStarted: lockDeadline.restart()
        stdout: SplitParser {
            onRead: data => {
                const state = data.trim();
                root.lockState = state === "unlocked" || state === "locked" ? state : "unknown";
                if (root.lockState === "unlocked") { lockDeadline.stop(); root.finishOpen(); }
                else if (root.lockState === "locked") { lockDeadline.stop(); root.closeProbe("lock-locked"); }
                else if (root.opened) root.closeProbe("lock-unknown");
            }
        }
        stderr: StdioCollector {}
        onExited: {
            lockDeadline.stop();
            root.lockState = "unknown";
            root.closeProbe("lock-unavailable");
        }
    }
    Timer {
        id: lockDeadline
        interval: 3500
        onTriggered: {
            root.lockState = "unknown";
            root.closeProbe("lock-timeout");
            lockCheck.signal(9);
        }
    }
    Timer {
        id: captureDeadline
        interval: 2000
        onTriggered: {
            root.captureTarget = null;
            root.result = "capture-timeout";
        }
    }
    Timer { id: autoClose; interval: 15000; onTriggered: root.closeProbe("auto-closed") }
    Connections {
        target: root.captureTarget
        function onClosed() {
            root.captureTarget = null;
            root.result = "fixture-closed";
            captureDeadline.stop();
        }
    }

    // Inspect the actual captured fixture in memory. No screenshots are saved.
    TestResult { id: pixels }
    function inspectFrame() {
        if (!opened || lockState !== "unlocked" || !capture.hasContent) return false;
        // QtTest's grabImage uses local x/y, not ancestor-mapped coordinates.
        // Grab this probe's content item and sample the capture's mapped rect.
        const image = pixels.grabImage(panel.contentItem);
        if (image.width < 2 || image.height < 2) { pixelCheck = "empty-readback"; return false; }
        const origin = capture.mapToItem(panel.contentItem, 0, 0);
        const scale = image.width / panel.width;
        const expected = [[204, 51, 68], [51, 187, 102], [51, 102, 221], [238, 221, 68]];
        for (let i = 0; i < expected.length; i++) {
            const x = Math.floor((origin.x + capture.width * (i % 2 ? 0.75 : 0.25)) * scale);
            const y = Math.floor((origin.y + capture.height * (i > 1 ? 0.75 : 0.25)) * scale);
            if (Math.abs(image.red(x, y) - expected[i][0]) > 12
                || Math.abs(image.green(x, y) - expected[i][1]) > 12
                || Math.abs(image.blue(x, y) - expected[i][2]) > 12) {
                const r = image.red(x, y), g = image.green(x, y), b = image.blue(x, y);
                const classification = image.alpha(x, y) < 128 ? "transparent" : Math.max(r,g,b) < 30 ? "black"
                    : r > g * 1.3 && r > b * 1.3 ? "red" : g > r * 1.3 && g > b * 1.3 ? "green"
                    : b > r * 1.3 && b > g * 1.3 ? "blue" : r > b * 1.3 && g > b * 1.3 ? "yellow" : "other";
                pixelCheck = "quadrant-" + i + "-mismatch-" + classification;
                return false;
            }
        }
        pixelCheck = "verified";
        return true;
    }

    // Read back only the preview area, in memory, for an explicitly opened
    // application window. This does not inspect the surrounding desktop.
    function inspectApplicationFrame() {
        if (!opened || lockState !== "unlocked" || !capture.hasContent) return false;
        const image = pixels.grabImage(panel.contentItem);
        const origin = capture.mapToItem(panel.contentItem, 0, 0);
        const scale = image.width / panel.width;
        let darkest = 255, lightest = 0;
        for (let row = 1; row < 40; row++) {
            for (let col = 1; col < 40; col++) {
                const x = Math.floor((origin.x + capture.width * col / 40) * scale);
                const y = Math.floor((origin.y + capture.height * row / 40) * scale);
                if (image.alpha(x, y) < 128) continue;
                const value = (image.red(x, y) + image.green(x, y) + image.blue(x, y)) / 3;
                darkest = Math.min(darkest, value);
                lightest = Math.max(lightest, value);
            }
        }
        return lightest - darkest > 80;
    }

    PanelWindow {
        id: panel
        visible: root.opened
        implicitWidth: 720
        implicitHeight: 520
        color: "#293238"
        exclusionMode: ExclusionMode.Ignore
        WlrLayershell.namespace: "trackpad-plus-overview-probe"
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: root.opened ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
        screen: Quickshell.screens.find(s => Hyprland.focusedMonitor && s.name === Hyprland.focusedMonitor.name) || Quickshell.screens[0]

        Rectangle {
            anchors.fill: parent
            color: "transparent"
            border.color: "#80b9b2"
            border.width: 2
            focus: true
            Keys.onEscapePressed: root.closeProbe("escape")
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 24
                spacing: 14
                Text { text: "Trackpad Plus · capture probe"; color: "#ded4b8"; font.pixelSize: 24 }
                Text { text: "Fixture only · Escape to close · closes automatically after 15 seconds"; color: "#ded4b8" }
                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    ScreencopyView {
                        id: capture
                        anchors.centerIn: parent
                        constraintSize: Qt.size(parent.width, parent.height)
                        captureSource: root.opened ? root.captureTarget : null
                        live: false
                        paintCursor: false
                        onHasContentChanged: {
                            if (hasContent && root.opened && root.lockState === "unlocked") {
                                root.latencyMs = Date.now() - root.startedAt;
                                root.result = "frame-ready";
                                captureDeadline.stop();
                            }
                        }
                        onStopped: {
                            root.captureTarget = null;
                            if (root.opened) root.result = "capture-stopped";
                            captureDeadline.stop();
                        }
                    }
                }
                Text { text: root.result; color: "#ded4b8"; font.pixelSize: 18 }
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 42
                    color: "#414b50"
                    Text { anchors.centerIn: parent; text: "Close"; color: "#ded4b8" }
                    MouseArea { anchors.fill: parent; onClicked: root.closeProbe("button") }
                }
            }
        }
    }
    IpcHandler {
        target: "overviewProbe"
        function open(address: string): string { return root.requestOpen(address); }
        function close(): void { root.closeProbe("ipc-close"); }
        function checkPixels(): bool { return root.inspectFrame(); }
        function checkApplicationPixels(): bool { return root.inspectApplicationFrame(); }
        function status(): string {
            return JSON.stringify({ opened: root.opened, pending: root.pending, result: root.result,
                lockState: root.lockState, hasContent: capture.hasContent,
                width: capture.sourceSize.width, height: capture.sourceSize.height,
                captureAttached: root.captureTarget !== null, latencyMs: root.latencyMs,
                opens: root.openCount, closes: root.closeCount, pixelCheck: root.pixelCheck });
        }
    }
}
