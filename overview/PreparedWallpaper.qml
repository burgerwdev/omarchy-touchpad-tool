import QtQuick

// Keep this item alive while the overview is hidden. Only wallpaper pixels are
// retained; the view's window captures have a separate, shorter lifetime.
Item {
    id: wallpaper
    objectName: "preparedWallpaper"
    property url source: ""
    property real pixelRatio: 1
    property bool requested: false
    property bool resolving: false
    property int fallbackDelay: 1000
    property color fallbackColor: "#293238"
    property bool fallbackLatched: false
    property bool preparedForOpen: false
    readonly property bool ready: !resolving && image.status === Image.Ready
    readonly property bool presentable: requested && (preparedForOpen || fallbackLatched)
    readonly property int imageStatus: image.status
    onRequestedChanged: {
        preparedForOpen = requested && ready;
        if (!requested) fallbackLatched = false;
    }
    // Mapping may reload the image at the window's actual device-pixel ratio.
    // Retain those pixels while loading; never hide/remap an already shown view.
    onReadyChanged: { if (requested && ready) preparedForOpen = true; }

    Rectangle { anchors.fill: parent; color: wallpaper.fallbackColor }
    Image {
        id: image
        anchors.fill: parent
        source: wallpaper.source
        sourceSize: Qt.size(Math.max(1, Math.min(4096, Math.ceil(width * wallpaper.pixelRatio))),
                            Math.max(1, Math.min(4096, Math.ceil(height * wallpaper.pixelRatio))))
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: false
        retainWhileLoading: true
        // A timed-out load must not replace an already visible fallback later.
        visible: !wallpaper.fallbackLatched
    }
    Timer {
        interval: wallpaper.fallbackDelay
        running: wallpaper.requested && !wallpaper.presentable
        onTriggered: wallpaper.fallbackLatched = true
    }
}
