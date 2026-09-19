import QtQuick
import Quickshell
import Quickshell.Io
import QtTest

// Real Wayland windows with known, non-private content. They are the capture
// source, never a substitute image injected into the probe's preview.
ShellRoot {
    id: root
    property int presentations: 0
    component Fixture: FloatingWindow {
        id: fixture
        property string label
        title: "Trackpad Plus probe " + label
        visible: true
        implicitWidth: 560
        implicitHeight: 360
        color: "white"
        Item {
            anchors.fill: parent
            Rectangle { width: parent.width / 2; height: parent.height / 2; color: "#cc3344" }
            Rectangle { x: width; width: parent.width / 2; height: parent.height / 2; color: "#33bb66" }
            Rectangle { y: height; width: parent.width / 2; height: parent.height / 2; color: "#3366dd" }
            Rectangle { x: width; y: height; width: parent.width / 2; height: parent.height / 2; color: "#eedd44" }
        }
        Text {
            anchors.centerIn: parent
            text: fixture.label + " ↑"
            font.pixelSize: 80
            color: "white"
            style: Text.Outline
            styleColor: "black"
        }
    }
    Fixture { id: fixtureA; label: "A" }
    Fixture { label: "B" }
    TestResult { id: pixels }
    Connections {
        target: fixtureA.contentItem.Window.window
        function onFrameSwapped() { root.presentations++; }
    }
    IpcHandler {
        target: "fixture"
        function requestPresent(): int {
            const before = root.presentations;
            fixtureA.contentItem.Window.window.update();
            return before;
        }
        function presentationCount(): int { return root.presentations; }
        function sourceStatus(): string {
            const image = pixels.grabImage(fixtureA.contentItem);
            const samples = [];
            for (let i = 0; i < 4; i++) {
                const x = Math.floor(image.width * (i % 2 ? 0.75 : 0.25));
                const y = Math.floor(image.height * (i > 1 ? 0.75 : 0.25));
                samples.push([image.red(x, y), image.green(x, y), image.blue(x, y)]);
            }
            return JSON.stringify({width: fixtureA.width, height: fixtureA.height,
                x: fixtureA.contentItem.x, y: fixtureA.contentItem.y,
                contentWidth: fixtureA.contentItem.width, contentHeight: fixtureA.contentItem.height,
                dpr: fixtureA.devicePixelRatio,
                imageWidth: image.width, imageHeight: image.height, samples: samples});
        }
        function checkSource(): bool {
            const image = pixels.grabImage(fixtureA.contentItem);
            if (image.width < 2 || image.height < 2) return false;
            const dpr = fixtureA.devicePixelRatio;
            if (Math.abs(image.width - fixtureA.contentItem.width * dpr) > 1
                || Math.abs(image.height - fixtureA.contentItem.height * dpr) > 1) return false;
            const expected = [[204, 51, 68], [51, 187, 102], [51, 102, 221], [238, 221, 68]];
            for (let i = 0; i < expected.length; i++) {
                const x = Math.floor(image.width * (i % 2 ? 0.75 : 0.25));
                const y = Math.floor(image.height * (i > 1 ? 0.75 : 0.25));
                if (Math.abs(image.red(x, y) - expected[i][0]) > 12
                    || Math.abs(image.green(x, y) - expected[i][1]) > 12
                    || Math.abs(image.blue(x, y) - expected[i][2]) > 12) return false;
            }
            return true;
        }
    }
}
