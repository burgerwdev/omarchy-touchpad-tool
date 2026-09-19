pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

FocusScope {
    id: view
    property var snapshot: ({workspaces: []})
    property var sourceFor: function(entry) { return null; }
    property bool captureEnabled: true
    property url wallpaperSource: ""
    property bool paintWallpaper: true
    property color foreground: "#ded4b8"
    property color backgroundColor: "#293238"
    property color accent: "#80b9b2"
    readonly property var activeWorkspace: snapshot.workspaces.find(w => w.active) || null
    readonly property string activeKey: activeWorkspace ? activeWorkspace.key : ""
    readonly property int windowCount: activeWorkspace ? activeWorkspace.windows.length : 0
    readonly property int windowsPerPage: 6
    readonly property int windowsPerThumbnail: 3
    property int windowPage: 0
    readonly property int windowPageCount: Math.max(1, Math.ceil(windowCount / windowsPerPage))
    readonly property int columns: width < 900 ? 2 : 3
    onActiveKeyChanged: {
        windowPage = activeWorkspace ? Math.max(0, Math.floor(activeWorkspace.windows.findIndex(w => w.active) / windowsPerPage)) : 0;
        revealWorkspace.restart();
    }
    onWindowPageCountChanged: windowPage = Math.min(windowPage, windowPageCount - 1)
    property int inFlight: 0
    property var cards: []
    property int readyCount: 0
    signal createWorkspace()
    signal dismiss()
    signal selected(string kind, string key)
    focus: true
    Keys.onEscapePressed: dismiss()
    // Tab follows all visible controls; arrows move within the same order.
    Keys.onPressed: event => {
        if (event.key === Qt.Key_Left || event.key === Qt.Key_Up) {
            const item = activeFocusItem();
            if (item) moveFocus(item, false);
            event.accepted = true;
        } else if (event.key === Qt.Key_Right || event.key === Qt.Key_Down) {
            const item = activeFocusItem();
            if (item) moveFocus(item, true);
            event.accepted = true;
        } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
            const item = activeFocusItem();
            if (item && item.enabled && typeof item.clicked === "function") item.clicked();
            event.accepted = true;
        }
    }
    function moveFocus(item, forward) {
        let next = item.nextItemInFocusChain(forward);
        while (next && next !== item) {
            if (next.visible && next.enabled && next.activeFocusOnTab) { next.forceActiveFocus(); return; }
            next = next.nextItemInFocusChain(forward);
        }
    }
    function activeFocusItem() { return Window.window ? Window.window.activeFocusItem : null; }
    // Coalesce newly built delegates into the next event turn, without waiting
    // for the periodic capture-completion poll to start the first previews.
    function enqueue(card) { cards = cards.concat([card]); Qt.callLater(view.startQueued); }
    function startQueued() {
        const live = cards.filter(card => card && card.captureState !== undefined && card.captureState !== "retired");
        let active = live.filter(card => card.captureState === "capturing").length;
        for (let card of live) {
            if (active >= 2) break;
            if (card.captureState !== "waiting") continue;
            card.beginCapture();
            if (card.captureState === "capturing") active++;
        }
        cards = live;
        inFlight = active;
        readyCount = live.filter(card => card.captureState === "ready").length;
        pump.running = active > 0 || live.some(card => card.captureState === "waiting");
    }
    Timer { id: pump; interval: 30; repeat: true; onTriggered: view.startQueued() }
    onSnapshotChanged: pump.start()
    Timer {
        id: revealWorkspace
        interval: 0
        onTriggered: {
            const index = view.snapshot.workspaces.findIndex(w => w.active);
            if (index >= 0) strip.positionViewAtIndex(index, ListView.Contain);
        }
    }
    Component.onCompleted: revealWorkspace.start()
    function thumbnailWindows(workspace) {
        // Keep the focused window in the limited miniature and paint it last.
        const active = workspace.windows.find(w => w.active);
        const others = workspace.windows.filter(w => w !== active);
        return active ? others.slice(0, windowsPerThumbnail - 1).concat([active]) : others.slice(0, windowsPerThumbnail);
    }
    function windowAspect(entry) {
        const g = entry.geometry;
        return g && g.width > 0 && g.height > 0 ? g.width * view.width / (g.height * view.height) : 1.6;
    }
    Rectangle { anchors.fill: parent; color: view.backgroundColor; visible: view.paintWallpaper }
    component WallpaperImage: Image {
        source: view.wallpaperSource
        sourceSize: Qt.size(Math.ceil(width * 2), Math.ceil(height * 2))
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: true
    }
    WallpaperImage {
        objectName: "desktopWallpaper"
        anchors.fill: parent
        visible: view.paintWallpaper
        source: view.paintWallpaper ? view.wallpaperSource : ""
    }
    Item {
        id: topPanel
        objectName: "workspacePanel"
        width: parent.width
        height: Math.max(110, Math.min(240, view.height * 0.18))
        y: -height
        Component.onCompleted: entrance.start()
        NumberAnimation { id: entrance; target: topPanel; property: "y"; to: 0; duration: 260; easing.type: Easing.OutCubic }
        Rectangle { anchors.fill: parent; color: "#66303946" }
        ListView {
            id: strip
            objectName: "workspaceStrip"
            anchors.centerIn: parent
            width: Math.min(1320, parent.width - 48, (count + 1) * (cardWidth + 12))
            height: parent.height - 24
            orientation: ListView.Horizontal
            spacing: 12
            clip: true
            // Lightweight buttons remain in the focus chain. Only intersecting
            // desktop Loaders retain captures (at most 7 tiles × 3 windows).
            cacheBuffer: (count + 1) * (cardWidth + spacing)
            boundsBehavior: Flickable.StopAtBounds
            model: view.snapshot.workspaces
            readonly property real cardWidth: Math.max(136,
                (Math.min(1320, topPanel.width - 48) - 60) / 6,
                Math.min(320, height * view.width / Math.max(1, view.height)))
            ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }
            footer: Button {
                id: newWorkspace
                objectName: "newWorkspace"
                width: strip.cardWidth + 12
                height: strip.height
                leftPadding: 12
                Accessible.name: "Create workspace"
                hoverEnabled: true
                onActiveFocusChanged: { if (activeFocus) strip.positionViewAtEnd(); }
                onClicked: view.createWorkspace()
                background: Rectangle {
                    x: 12
                    width: parent.width - 12
                    height: parent.height
                    color: newWorkspace.hovered || newWorkspace.activeFocus ? "#665c6471" : "#44303946"
                    border.width: newWorkspace.activeFocus ? 2 : 0
                    border.color: view.accent
                }
                contentItem: Text { text: "+"; color: view.foreground; font.pixelSize: 64; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
            }
            delegate: Button {
                id: workspace
                required property var modelData
                required property int index
                onActiveFocusChanged: { if (activeFocus) strip.positionViewAtIndex(index, ListView.Contain); }
                objectName: "workspace-" + modelData.key
                width: strip.cardWidth
                height: strip.height
                padding: 0
                hoverEnabled: true
                Accessible.name: "Workspace " + modelData.name + (modelData.active ? ", current" : "")
                onClicked: view.selected("workspace", modelData.key)
                background: Rectangle { color: view.backgroundColor }
                contentItem: Item {
                    clip: true
                    Loader {
                        anchors.fill: parent
                        active: workspace.x + workspace.width > strip.contentX
                            && workspace.x < strip.contentX + strip.width
                        sourceComponent: Item {
                            id: miniature
                            WallpaperImage { anchors.fill: parent }
                            Repeater {
                                model: view.thumbnailWindows(workspace.modelData)
                                delegate: WindowCard {
                                    required property var modelData
                                    required property int index
                                    readonly property var geometry: modelData.geometry
                                    entry: modelData
                                    x: geometry ? geometry.x * miniature.width : miniature.width * (0.08 + index * 0.06)
                                    y: geometry ? geometry.y * miniature.height : miniature.height * (0.1 + index * 0.07)
                                    width: geometry ? geometry.width * miniature.width : miniature.width * 0.76
                                    height: geometry ? geometry.height * miniature.height : miniature.height * 0.76
                                    source: view.sourceFor(entry)
                                    captureEnabled: view.captureEnabled
                                    compact: true
                                    desktopStyle: true
                                    enabled: false
                                    foreground: view.foreground
                                    backgroundColor: view.backgroundColor
                                    accent: view.accent
                                    onQueued: card => view.enqueue(card)
                                }
                            }
                        }
                    }
                    Rectangle {
                        anchors.fill: parent
                        color: "transparent"
                        border.width: workspace.modelData.active || workspace.hovered || workspace.activeFocus ? 2 : 0
                        border.color: view.accent
                    }
                    Text {
                        anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter; bottomMargin: 5 }
                        text: "Workspace " + workspace.modelData.name + (workspace.modelData.windows.length > view.windowsPerThumbnail ? "  +" + (workspace.modelData.windows.length - view.windowsPerThumbnail) : "")
                        textFormat: Text.PlainText
                        color: view.foreground
                        style: Text.Outline
                        styleColor: "#a0000000"
                        font.pixelSize: 12
                    }
                }
            }
        }
    }
    Item {
        id: windowArea
        anchors { top: topPanel.bottom; bottom: pager.top; left: parent.left; right: parent.right; margins: 28 }
        readonly property var windows: view.activeWorkspace ? view.activeWorkspace.windows.slice(view.windowPage * view.windowsPerPage, (view.windowPage + 1) * view.windowsPerPage) : []
        readonly property int columnCount: Math.max(1, Math.min(view.columns, windows.length))
        readonly property int rowCount: Math.max(1, Math.ceil(windows.length / columnCount))
        readonly property real cellWidth: width / columnCount
        readonly property real cellHeight: height / rowCount
        Repeater {
            model: windowArea.windows
            delegate: Item {
                id: slot
                required property var modelData
                required property int index
                readonly property int row: Math.floor(index / windowArea.columnCount)
                readonly property int rowItems: Math.min(windowArea.columnCount, windowArea.windows.length - row * windowArea.columnCount)
                x: (windowArea.width - rowItems * windowArea.cellWidth) / 2 + (index % windowArea.columnCount) * windowArea.cellWidth
                y: row * windowArea.cellHeight
                width: windowArea.cellWidth
                height: windowArea.cellHeight
                WindowCard {
                    entry: slot.modelData
                    anchors.centerIn: parent
                    readonly property real aspect: view.windowAspect(entry)
                    width: Math.min(parent.width * 0.94, parent.height * 0.9 * aspect)
                    height: width / aspect
                    source: view.sourceFor(entry)
                    captureEnabled: view.captureEnabled
                    desktopStyle: true
                    foreground: view.foreground
                    backgroundColor: view.backgroundColor
                    accent: view.accent
                    onQueued: card => view.enqueue(card)
                    onClicked: view.selected("window", entry.key)
                }
            }
        }
        Text {
            objectName: "emptyWorkspace"
            anchors.centerIn: parent
            text: view.activeWorkspace ? "This workspace is empty" : "Select a workspace above"
            visible: view.windowCount === 0
            color: view.foreground
            style: Text.Outline
            styleColor: "#a0000000"
        }
    }
    RowLayout {
        id: pager
        anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter; bottomMargin: 12 }
        height: view.windowPageCount > 1 ? implicitHeight : 0
        visible: view.windowPageCount > 1
        Button { objectName: "previousWindows"; text: "‹"; Accessible.name: "Previous windows"; enabled: view.windowPage > 0; onClicked: view.windowPage-- }
        Text { text: (view.windowPage + 1) + " / " + view.windowPageCount; color: view.foreground }
        Button { objectName: "nextWindows"; text: "›"; Accessible.name: "Next windows"; enabled: view.windowPage + 1 < view.windowPageCount; onClicked: view.windowPage++ }
    }
}
