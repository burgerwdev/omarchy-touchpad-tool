import QtQuick
import Quickshell.Wayland

Item {
    id: preview
    property var captureSource: null
    signal ready()
    signal failed()
    ScreencopyView {
        anchors.centerIn: parent
        constraintSize: Qt.size(parent.width, parent.height)
        captureSource: preview.captureSource
        live: false
        paintCursor: false
        onHasContentChanged: { if (hasContent) preview.ready(); }
        onStopped: preview.failed()
    }
}
