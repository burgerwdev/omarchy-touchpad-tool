import QtQuick
import QtQuick.Controls
import QtTest
import "overview"

TestCase {
    id: test
    name: "Overview"
    visible: true
    when: windowShown
    width: 1100
    height: 850
    Component { id: component; Overview { width: 1100; height: 850; captureEnabled: false } }
    property var view
    function init() {
        let groups = [];
        for (let i = 1; i <= 7; i++) groups.push({key: "w" + i, id: i, name: String(i), active: i === 1,
            windows: i === 1 ? [{key: "a", title: "<b>Plain title</b>", appId: "app", active: true}] : []});
        view = createTemporaryObject(component, test, {snapshot: {workspaces: groups}});
        verify(view);
        view.forceActiveFocus();
        wait(30);
    }
    function test_workspace_strip_and_current_windows() {
        const strip = findChild(view, "workspaceStrip");
        verify(strip);
        compare(strip.count, 7);
        compare(view.activeWorkspace.id, 1);
        compare(view.windowCount, 1);
        const spy = createTemporaryObject(spyComponent, test, {target: view, signalName: "selected"});
        mouseClick(findChild(view, "workspace-w2"));
        compare(spy.count, 1);
        compare(spy.signalArguments[0][0], "workspace");
        compare(spy.signalArguments[0][1], "w2");
        // Content follows compositor acknowledgement, not a speculative click.
        compare(view.activeWorkspace.id, 1);
        const groups = view.snapshot.workspaces.map(w => Object.assign({}, w, {active: w.id === 2}));
        view.snapshot = {workspaces: groups};
        compare(view.activeWorkspace.id, 2);
        compare(view.windowCount, 0);
        verify(findChild(view, "emptyWorkspace").visible);
        compare(findChild(view, "nextPage"), null);
    }
    function test_strip_overflow_and_window_paging() {
        view.width = 700;
        const strip = findChild(view, "workspaceStrip");
        verify(strip.contentWidth > strip.width);
        const windows = [];
        for (let i = 0; i < 9; i++) windows.push({key: "window" + i, title: "Window " + i});
        view.snapshot = {workspaces: [{key: "w9", id: 9, name: "9", active: true, windows: windows}]};
        compare(view.windowPageCount, 2);
        mouseClick(findChild(view, "nextWindows"));
        compare(view.windowPage, 1);
        view.snapshot = {workspaces: [{key: "w9", id: 9, name: "9", active: true, windows: windows.slice(0, 1)}]};
        compare(view.windowPage, 0);
    }
    function test_failed_capture_remains_selectable() {
        const spy = createTemporaryObject(spyComponent, test, {target: view, signalName: "selected"});
        const cards = [];
        function walk(item) {
            if (item.captureState !== undefined && !item.compact) cards.push(item);
            for (let child of item.children) walk(child);
        }
        walk(view);
        compare(cards.length, 1);
        tryCompare(cards[0], "captureState", "unavailable");
        mouseClick(cards[0]);
        compare(spy.count, 1);
        compare(spy.signalArguments[0][0], "window");
        compare(spy.signalArguments[0][1], "a");
        compare(view.inFlight, 0);
        cards[0].forceActiveFocus();
        keyClick(Qt.Key_Return);
        compare(spy.count, 2);
        keyClick(Qt.Key_Right);
        verify(!cards[0].activeFocus);
    }
    function test_keyboard_reaches_all_overflow_workspaces() {
        view.width = 628; // Four 136px cards and three 12px gaps inside the margins.
        const groups = [];
        for (let i = 0; i < 20; i++) groups.push({key: "keys" + i, id: i + 1, name: String(i + 1), active: i === 0,
            windows: [{key: "keythumb" + i, title: "Window " + i}]});
        view.snapshot = {workspaces: groups};
        const strip = findChild(view, "workspaceStrip");
        tryCompare(strip, "width", 580);
        compare(strip.cardWidth, 136);
        tryVerify(() => findChild(view, "workspace-keys0") !== null);
        wait(30);
        findChild(view, "workspace-keys0").forceActiveFocus();
        for (const forward of [Qt.Key_Right, Qt.Key_Tab]) {
            for (let i = 1; i < 20; i++) {
                keyClick(forward);
                tryCompare(view.activeFocusItem(), "objectName", "workspace-keys" + i);
                verify(view.cards.filter(c => c && c.compact && c.captureState !== "retired").length <= 7);
            }
            verify(strip.contentX > 0);
            for (let i = 18; i >= 0; i--) {
                keyClick(forward === Qt.Key_Right ? Qt.Key_Left : Qt.Key_Backtab);
                tryCompare(view.activeFocusItem(), "objectName", "workspace-keys" + i);
                verify(view.cards.filter(c => c && c.compact && c.captureState !== "retired").length <= 7);
            }
            tryCompare(strip, "contentX", 0);
        }
    }
    function test_nonzero_window_page_survives_equivalent_snapshot() {
        const windows = [];
        for (let i = 0; i < 9; i++) windows.push({key: "stable" + i, title: "Window " + i, active: i === 0});
        const group = {key: "stable", id: 1, name: "1", active: true, windows: windows};
        view.snapshot = {workspaces: [group]};
        mouseClick(findChild(view, "nextWindows"));
        compare(view.windowPage, 1);
        for (const titleOnly of [false, true]) {
            const copy = JSON.parse(JSON.stringify(group));
            if (titleOnly) copy.windows[8].title = "Updated title";
            view.snapshot = {workspaces: [copy]};
            compare(view.windowPage, 1);
            tryVerify(() => view.cards.some(c => c && !c.compact && c.entry.key === "stable8"));
        }
    }
    function test_populated_strip_unloads_offscreen_previews() {
        const groups = [];
        for (let i = 0; i < 20; i++) groups.push({key: "strip" + i, id: i + 1, name: String(i + 1), active: i === 0,
            windows: [{key: "thumb" + i, title: "Window " + i}]});
        view.snapshot = {workspaces: groups};
        const strip = findChild(view, "workspaceStrip");
        tryVerify(() => view.cards.some(c => c && c.compact && c.entry.key === "thumb0"));
        for (let i = 0; i < 3; i++) {
            strip.positionViewAtEnd();
            tryVerify(() => !view.cards.some(c => c && c.compact && c.captureState !== "retired" && c.entry.key === "thumb0"));
            tryVerify(() => view.cards.filter(c => c && c.compact && c.captureState !== "retired").length <= 7);
            strip.positionViewAtBeginning();
            tryVerify(() => view.cards.some(c => c && c.compact && c.entry.key === "thumb0"));
        }
        tryCompare(view, "inFlight", 0);
    }
    function test_quick_workspace_changes_select_active_window_page() {
        const windows = [];
        for (let i = 0; i < 9; i++) windows.push({key: "quick" + i, title: "Window " + i, active: i === 8});
        for (let id = 10; id <= 15; id++) {
            view.snapshot = {workspaces: [{key: "rapid" + id, id: id, name: String(id), active: true, windows: windows}]};
        }
        compare(view.activeWorkspace.id, 15);
        compare(view.windowPage, 1);
        tryVerify(() => view.cards.some(c => c && !c.compact && c.entry.key === "quick8"));
        const spy = createTemporaryObject(spyComponent, test, {target: view, signalName: "dismiss"});
        keyClick(Qt.Key_Escape);
        compare(spy.count, 1);
        compare(view.activeWorkspace.id, 15);
    }
    function test_desktop_composition_and_window_aspect() {
        const windows = [
            {key: "left", title: "Left", geometry: {x: 0.05, y: 0.1, width: 0.4, height: 0.8}},
            {key: "right", title: "Right", geometry: {x: 0.55, y: 0.1, width: 0.4, height: 0.8}},
            {key: "hidden", title: "Omitted"},
            {key: "focused", title: "Focused", active: true, geometry: {x: 0.25, y: 0.25, width: 0.5, height: 0.5}}
        ];
        view.snapshot = {workspaces: [{key: "composed", id: 1, name: "1", active: true, windows: windows}]};
        tryCompare(findChild(view, "workspacePanel"), "y", 0);
        tryVerify(() => view.cards.filter(c => c && c.compact && c.captureState !== "retired").length === 3);
        const miniatures = view.cards.filter(c => c && c.compact && c.captureState !== "retired");
        compare(miniatures.map(c => c.entry.key).join(","), "left,right,focused");
        const left = miniatures[0];
        compare(left.x, left.parent.width * 0.05);
        compare(left.y, left.parent.height * 0.1);
        compare(left.width, left.parent.width * 0.4);
        compare(left.height, left.parent.height * 0.8);
        const main = view.cards.find(c => c && c.entry && !c.compact && c.entry.key === "left");
        verify(main);
        fuzzyCompare(main.width / main.height, 0.4 * view.width / (0.8 * view.height), 0.001);
        verify(main.desktopStyle);
        const wallpaper = findChild(view, "desktopWallpaper");
        verify(wallpaper);
        compare(wallpaper.width, view.width);
        compare(wallpaper.height, view.height);
        const spy = createTemporaryObject(spyComponent, test, {target: view, signalName: "createWorkspace"});
        const plus = findChild(view, "newWorkspace");
        mouseClick(plus);
        compare(spy.count, 1);
        plus.forceActiveFocus();
        keyClick(Qt.Key_Return);
        compare(spy.count, 2);
    }
    function test_three_window_thumbnail_capture_bound() {
        const groups = [];
        for (let i = 0; i < 20; i++) groups.push({key: "bounded" + i, id: i + 1, name: String(i + 1), active: i === 0,
            windows: [0, 1, 2, 3].map(j => ({key: "bounded" + i + "-" + j, title: "Window", active: j === 3}))});
        view.snapshot = {workspaces: groups};
        const strip = findChild(view, "workspaceStrip");
        tryVerify(() => view.cards.some(c => c && c.compact && c.entry.key === "bounded0-0"));
        verify(view.cards.filter(c => c && c.compact && c.captureState !== "retired").length <= 21);
        strip.positionViewAtEnd();
        tryVerify(() => !view.cards.some(c => c && c.compact && c.captureState !== "retired" && c.entry.key === "bounded0-0"));
        verify(view.cards.filter(c => c && c.compact && c.captureState !== "retired").length <= 21);
        strip.positionViewAtBeginning();
        tryVerify(() => view.cards.some(c => c && c.compact && c.entry.key === "bounded0-0"));
        tryVerify(() => view.cards.filter(c => c && c.captureState !== "retired").length <= 27);
    }
    function test_visible_thumbnails_are_created() {
        tryVerify(() => view.cards.some(c => c && c.compact));
    }
    function test_escape() {
        const spy = createTemporaryObject(spyComponent, test, {target: view, signalName: "dismiss"});
        keyClick(Qt.Key_Escape);
        compare(spy.count, 1);
    }
    function test_removed_workspace_does_not_choose_another() {
        view.snapshot = {workspaces: view.snapshot.workspaces.slice(1)};
        compare(view.activeWorkspace, null);
        compare(view.windowCount, 0);
        view.snapshot = {workspaces: []};
        compare(view.windowPage, 0);
    }
    Component {
        id: pendingCard
        QtObject {
            property string captureState: "waiting"
            function beginCapture() { captureState = "capturing"; }
        }
    }
    function test_removed_inflight_cards_release_slots() {
        const first = pendingCard.createObject(test);
        const second = pendingCard.createObject(test);
        const third = createTemporaryObject(pendingCard, test);
        view.enqueue(first); view.enqueue(second); view.enqueue(third);
        tryCompare(view, "inFlight", 2);
        compare(third.captureState, "waiting");
        first.destroy(); second.destroy();
        tryCompare(third, "captureState", "capturing");
        compare(view.inFlight, 1);
        third.captureState = "ready";
        tryCompare(view, "inFlight", 0);
    }
    function test_new_captures_start_next_turn_with_two_slot_limit() {
        const cards = [0, 1, 2].map(() => createTemporaryObject(pendingCard, test));
        for (const card of cards) view.enqueue(card);
        let states = null;
        Qt.callLater(() => { states = cards.map(card => card.captureState).join(","); });
        tryVerify(() => states !== null);
        compare(states, "capturing,capturing,waiting");
    }
    Component { id: wallpaperComponent; PreparedWallpaper { width: 1100; height: 850 } }
    function test_prepared_wallpaper_first_frame_and_reopen() {
        const wallpaper = createTemporaryObject(wallpaperComponent, test, {
            source: Qt.resolvedUrl("assets/screenshots/trackpad-controls.png"), requested: true
        });
        const statusAtConstruction = wallpaper.imageStatus;
        if (statusAtConstruction !== Image.Ready) verify(!wallpaper.presentable);
        tryCompare(wallpaper, "ready", true);
        verify(wallpaper.presentable);
        const first = grabImage(wallpaper).pixel(20, 600);
        // Mapping can reload the image for the actual window scale. Once shown,
        // retain its pixels instead of hiding/remapping the window in a loop.
        wallpaper.resolving = true;
        compare(wallpaper.ready, false);
        compare(wallpaper.presentable, true);
        wallpaper.resolving = false;
        wallpaper.requested = false;
        compare(wallpaper.presentable, false);
        compare(wallpaper.imageStatus, Image.Ready);
        wallpaper.requested = true;
        compare(wallpaper.presentable, true);
        compare(grabImage(wallpaper).pixel(20, 600), first);
    }
    function test_wallpaper_timeout_is_stable_and_close_cancels_presentation() {
        const wallpaper = createTemporaryObject(wallpaperComponent, test, {
            requested: true, resolving: true, fallbackDelay: 30
        });
        compare(wallpaper.presentable, false);
        tryCompare(wallpaper, "fallbackLatched", true);
        const fallback = grabImage(wallpaper).pixel(20, 600);
        wallpaper.source = Qt.resolvedUrl("assets/screenshots/trackpad-controls.png");
        wallpaper.resolving = false;
        tryCompare(wallpaper, "ready", true);
        compare(grabImage(wallpaper).pixel(20, 600), fallback);
        wallpaper.requested = false;
        compare(wallpaper.presentable, false);
        compare(wallpaper.fallbackLatched, false);
        wallpaper.resolving = true;
        wallpaper.requested = true;
        compare(wallpaper.presentable, false);
        wallpaper.requested = false; // Also represents the lock guard becoming false.
        wallpaper.resolving = false;
        wait(50);
        compare(wallpaper.presentable, false);
        compare(wallpaper.fallbackLatched, false);
    }
    Component { id: spyComponent; SignalSpy {} }
}
