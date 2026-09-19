import QtQuick
import Quickshell
import Quickshell.Io

// Visibility is permission to build the view, not proof that a frame rendered.
// The view destroys all capture objects when opened becomes false.
Item {
    id: session
    readonly property string token: Quickshell.env("TRACKPAD_OVERVIEW_TOKEN")
    readonly property string sessionIdentity: Quickshell.env("TRACKPAD_OVERVIEW_SESSION")
    readonly property string appVersion: Quickshell.env("TRACKPAD_OVERVIEW_VERSION")

    function authorized(candidate) {
        return /^[0-9a-f]{64}$/.test(token) && candidate === token && sessionIdentity !== "" && appVersion !== "";
    }
    function statusJson() {
        return JSON.stringify({ protocol: 1, version: appVersion, session: sessionIdentity,
            pid: Quickshell.processId, instance: Quickshell.instanceId,
            config: Quickshell.shellPath("shell.qml"), opened: session.opened,
            pending: session.pending, lockState: session.lockState,
            rendered: session.rendered, mapped: session.mapped, captures: session.captures,
            ready: session.ready, opens: session.openCount, closes: session.closeCount, result: session.result });
    }
    function denied() { return JSON.stringify({ error: "unauthorized" }); }


    property bool opened: false
    property bool pending: false
    property string lockState: "unknown"
    property string result: "hidden"
    property bool rendered: false
    property bool mapped: false
    property int captures: 0
    property int ready: 0
    property int openCount: 0
    property int closeCount: 0
    property bool initializingLock: true
    signal willOpen()
    signal closed(string reason)

    function dismiss(reason) {
        pending = false;
        opened = false;
        rendered = false;
        mapped = false;
        captures = 0;
        ready = 0;
        result = reason;
        closeCount++;
        closed(reason);
    }

    function finishOpen() {
        if (!pending || lockState !== "unlocked") return;
        willOpen();
        if (!pending || lockState !== "unlocked") return;
        pending = false;
        opened = true;
        result = "opened";
        openCount++;
    }

    function requestOpen() {
        if (opened && lockState === "unlocked") return;
        pending = true;
        result = "checking-lock";
        if (!lockCheck.running) {
            lockState = "unknown";
            initializingLock = true;
            lockCheck.running = true;
        } else if (lockState === "unlocked") finishOpen();
        else if (lockState === "locked") dismiss("locked");
    }

    Process {
        id: lockCheck
        command: ["python3", Quickshell.shellPath("lock-watch.py"), "--format", "plain", "--exit-on-consumer-close"]
        running: true
        onStarted: lockDeadline.restart()
        stdout: SplitParser {
            onRead: data => {
                const state = data.trim();
                session.lockState = state === "unlocked" || state === "locked" ? state : "unknown";
                if (session.lockState !== "unknown") {
                    session.initializingLock = false;
                    lockDeadline.stop();
                    if (session.lockState === "unlocked") session.finishOpen();
                    else session.dismiss("locked");
                } else if (!session.initializingLock || session.opened) {
                    session.dismiss("lock-unknown");
                }
            }
        }
        onExited: {
            lockDeadline.stop();
            session.initializingLock = false;
            session.lockState = "unknown";
            session.dismiss("lock-unavailable");
        }
    }
    Timer {
        id: lockDeadline
        interval: 3500
        onTriggered: {
            session.initializingLock = false;
            session.lockState = "unknown";
            session.dismiss("lock-timeout");
            lockCheck.signal(9);
        }
    }
    Timer { id: stopDelay; interval: 50; onTriggered: Qt.quit() }
    IpcHandler {
        target: "trackpadOverview"
        function status(): string { return session.statusJson(); }
        function open(token: string): string {
            if (!session.authorized(token)) return session.denied();
            session.requestOpen();
            return session.statusJson();
        }
        function close(token: string): string {
            if (!session.authorized(token)) return session.denied();
            session.dismiss("closed");
            return session.statusJson();
        }
        function toggle(token: string): string {
            if (!session.authorized(token)) return session.denied();
            if (session.opened || session.pending) session.dismiss("closed");
            else session.requestOpen();
            return session.statusJson();
        }
        function stop(token: string): string {
            if (!session.authorized(token)) return session.denied();
            session.dismiss("stopping");
            stopDelay.restart();
            return session.statusJson();
        }
    }
}
