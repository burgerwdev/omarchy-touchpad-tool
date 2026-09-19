pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls

Button {
    id: card
    required property var entry
    property bool compact: false
    property bool desktopStyle: false
    property var source: null
    property bool captureEnabled: true
    property color foreground: "#ded4b8"
    property color backgroundColor: "#343e43"
    property color accent: "#80b9b2"
    property string captureState: "waiting"
    signal queued(var card)
    Accessible.name: entry.title || entry.appId || "Window"
    hoverEnabled: true
    padding: desktopStyle ? 0 : (compact ? 2 : 8)

    function beginCapture() {
        if (captureState !== "waiting") return;
        if (!source || !captureEnabled) { finish("unavailable"); return; }
        captureState = "capturing";
        deadline.start();
    }
    function finish(state) {
        deadline.stop();
        captureState = state;
    }
    Component.onCompleted: queued(card)
    Component.onDestruction: captureState = "retired"
    onSourceChanged: { if (!source && captureState !== "waiting") finish("unavailable"); }
    Timer { id: deadline; interval: 2000; onTriggered: card.finish("unavailable") }
    background: Rectangle {
        color: card.desktopStyle && card.captureState === "ready" ? "transparent" : card.backgroundColor
        radius: card.desktopStyle ? 0 : 8
        border.width: card.hovered || card.activeFocus || card.entry.active ? 2 : (card.desktopStyle ? 0 : 1)
        border.color: card.hovered || card.activeFocus || card.entry.active ? card.accent : Qt.alpha(card.foreground, 0.25)
    }
    contentItem: Item {
        Item {
            anchors { top: parent.top; left: parent.left; right: parent.right; bottom: title.top; bottomMargin: card.compact || card.desktopStyle ? 0 : 8 }
            Loader {
                id: previewLoader
                anchors.fill: parent
                active: card.captureState === "capturing" || card.captureState === "ready"
                source: "Preview.qml"
                onLoaded: {
                    item.captureSource = Qt.binding(() => card.source);
                }
            }
            Connections {
                target: previewLoader.item
                ignoreUnknownSignals: true
                function onReady() { card.finish("ready"); }
                function onFailed() { card.finish("unavailable"); }
            }
            Text {
                anchors.centerIn: parent
                width: parent.width
                text: card.captureState === "unavailable" ? (card.compact ? "No preview" : "Preview unavailable\nSelect to open window") : "Loading…"
                visible: card.captureState !== "ready"
                color: Qt.alpha(card.foreground, 0.7)
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                textFormat: Text.PlainText
                font.pixelSize: card.compact ? 11 : 14
            }
        }
        Rectangle {
            anchors.fill: parent
            color: "transparent"
            visible: card.desktopStyle && !card.compact
            border.width: card.hovered || card.activeFocus || card.entry.active ? 2 : 1
            border.color: card.hovered || card.activeFocus || card.entry.active ? card.accent : Qt.alpha(card.foreground, 0.25)
        }
        Text {
            id: title
            visible: !card.compact && !card.desktopStyle
            height: card.compact || card.desktopStyle ? 0 : implicitHeight
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
            text: card.entry.title || card.entry.appId || "Window"
            textFormat: Text.PlainText
            elide: Text.ElideRight
            color: card.foreground
            font.pixelSize: card.compact ? 11 : 14
        }
    }
}
