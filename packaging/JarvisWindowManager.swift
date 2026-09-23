import AppKit
import ApplicationServices
import Foundation


/// Enumerates real AX windows and performs only bounded, reversible layouts.
final class JarvisWindowManager {
    private let launchableApplications: [(String, String)] = [
        ("com.conductor.app", "Conductor"),
        ("com.apple.Notes", "Notes"),
        ("company.thebrowser.Browser", "Arc"),
        ("notion.id", "Notion"),
        ("com.apple.iCal", "Calendar"),
        ("com.openai.codex", "ChatGPT"),
    ]
    private func attribute(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
        var value: CFTypeRef?
        return AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success
            ? value : nil
    }

    private func point(_ element: AXUIElement) -> CGPoint? {
        guard let raw = attribute(element, kAXPositionAttribute),
              CFGetTypeID(raw) == AXValueGetTypeID() else { return nil }
        var value = CGPoint.zero
        return AXValueGetValue(raw as! AXValue, .cgPoint, &value) ? value : nil
    }

    private func size(_ element: AXUIElement) -> CGSize? {
        guard let raw = attribute(element, kAXSizeAttribute),
              CFGetTypeID(raw) == AXValueGetTypeID() else { return nil }
        var value = CGSize.zero
        return AXValueGetValue(raw as! AXValue, .cgSize, &value) ? value : nil
    }

    private func set(_ element: AXUIElement, position: CGPoint, size: CGSize) -> Bool {
        var newSize = size
        var newPosition = position
        guard let sizeValue = AXValueCreate(.cgSize, &newSize),
              let positionValue = AXValueCreate(.cgPoint, &newPosition) else { return false }
        let sizeStatus = AXUIElementSetAttributeValue(element, kAXSizeAttribute as CFString, sizeValue)
        let positionStatus = AXUIElementSetAttributeValue(element, kAXPositionAttribute as CFString, positionValue)
        return sizeStatus == .success && positionStatus == .success
    }

    private func placed(_ element: AXUIElement, at position: CGPoint, size target: CGSize) -> Bool {
        guard let currentPosition = point(element), let currentSize = size(element) else {
            return false
        }
        return abs(currentPosition.x - position.x) < 35
            && abs(currentPosition.y - position.y) < 35
            && abs(currentSize.width - target.width) < 45
            && abs(currentSize.height - target.height) < 45
    }

    private func menuItem(_ element: AXUIElement, title: String, depth: Int = 0) -> AXUIElement? {
        guard depth < 6 else { return nil }
        if attribute(element, kAXTitleAttribute) as? String == title { return element }
        for child in (attribute(element, kAXChildrenAttribute) as? [AXUIElement]) ?? [] {
            if let found = menuItem(child, title: title, depth: depth + 1) { return found }
        }
        return nil
    }

    private func tileWithSystemMenu(_ app: NSRunningApplication, side: String) -> Bool {
        app.activate()
        let appElement = AXUIElementCreateApplication(app.processIdentifier)
        guard let rawMenu = attribute(appElement, kAXMenuBarAttribute),
              CFGetTypeID(rawMenu) == AXUIElementGetTypeID(),
              let windowMenu = menuItem(rawMenu as! AXUIElement, title: "Window") else {
            return false
        }
        _ = AXUIElementPerformAction(windowMenu, kAXPressAction as CFString)
        RunLoop.current.run(until: Date().addingTimeInterval(0.15))
        guard let resizeMenu = menuItem(windowMenu, title: "Move & Resize") else { return false }
        _ = AXUIElementPerformAction(resizeMenu, kAXPressAction as CFString)
        RunLoop.current.run(until: Date().addingTimeInterval(0.15))
        guard let sideItem = menuItem(resizeMenu, title: side == "left" ? "Left" : "Right") else {
            return false
        }
        return AXUIElementPerformAction(sideItem, kAXPressAction as CFString) == .success
    }

    private func fillWithSystemMenu(_ app: NSRunningApplication) -> Bool {
        app.activate()
        let appElement = AXUIElementCreateApplication(app.processIdentifier)
        guard let rawMenu = attribute(appElement, kAXMenuBarAttribute),
              CFGetTypeID(rawMenu) == AXUIElementGetTypeID(),
              let windowMenu = menuItem(rawMenu as! AXUIElement, title: "Window") else {
            return false
        }
        _ = AXUIElementPerformAction(windowMenu, kAXPressAction as CFString)
        RunLoop.current.run(until: Date().addingTimeInterval(0.15))
        guard let fillItem = menuItem(windowMenu, title: "Fill") else { return false }
        return AXUIElementPerformAction(fillItem, kAXPressAction as CFString) == .success
    }

    private struct Window {
        let id: String
        let element: AXUIElement
        let app: NSRunningApplication
        let title: String
        let frame: CGRect
    }

    private func windows() -> [Window] {
        var found: [Window] = []
        for app in NSWorkspace.shared.runningApplications {
            guard app.activationPolicy == .regular,
                  let bundleID = app.bundleIdentifier,
                  bundleID != "com.federico.jarvis" else { continue }
            let appElement = AXUIElementCreateApplication(app.processIdentifier)
            var appWindows = (attribute(appElement, kAXWindowsAttribute) as? [AXUIElement]) ?? []
            if appWindows.isEmpty,
               let focused = attribute(appElement, kAXFocusedWindowAttribute),
               CFGetTypeID(focused) == AXUIElementGetTypeID() {
                appWindows = [focused as! AXUIElement]
            }
            for (index, element) in appWindows.prefix(4).enumerated() {
                guard found.count < 30,
                      (attribute(element, kAXMinimizedAttribute) as? Bool) != true,
                      let origin = point(element), let dimensions = size(element),
                      dimensions.width >= 280, dimensions.height >= 180,
                      NSScreen.screens.contains(where: { $0.frame.intersects(CGRect(origin: origin, size: dimensions)) })
                else { continue }
                let title = ((attribute(element, kAXTitleAttribute) as? String) ?? "")
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                found.append(Window(
                    id: "window_\(app.processIdentifier)_\(index)", element: element,
                    app: app, title: String(title.prefix(160)),
                    frame: CGRect(origin: origin, size: dimensions)
                ))
            }
        }
        return found
    }

    func capture() -> [[String: Any]] {
        let actual = windows()
        var result: [[String: Any]] = actual.map { window in
            [
                "id": window.id,
                "app": window.app.localizedName ?? "",
                "bundle_id": window.app.bundleIdentifier ?? "",
                "title": window.title,
                "frame": [window.frame.minX, window.frame.minY,
                          window.frame.width, window.frame.height],
            ]
        }
        for (bundleID, name) in launchableApplications {
            guard !actual.contains(where: { $0.app.bundleIdentifier == bundleID }),
                  NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleID) != nil
            else { continue }
            result.append([
                "id": "launchable_\(bundleID)", "app": name,
                "bundle_id": bundleID, "title": "", "will_open": true,
            ])
        }
        return result
    }

    func tile(
        leftID: String, rightID: String,
        expectedLeft: String, expectedRight: String,
        expectedLeftTitle: String, expectedRightTitle: String,
        completion: @escaping ([String: Any]) -> Void
    ) {
        let requested: [(String, String)] = [
            (leftID, expectedLeft), (rightID, expectedRight),
        ].filter { $0.0.hasPrefix("launchable_") }
        guard requested.allSatisfy({ item in
            item.0 == "launchable_\(item.1)" &&
            launchableApplications.contains(where: { $0.0 == item.1 })
        }) else {
            completion(["ok": false, "error": "An application target is not approved for launch"])
            return
        }
        func prepare(_ index: Int) {
            guard index < requested.count else {
                let current = self.windows()
                func resolved(_ id: String, _ bundle: String, _ title: String) -> (String, String)? {
                    guard id.hasPrefix("launchable_") else { return (id, title) }
                    let matches = current.filter { $0.app.bundleIdentifier == bundle }
                    guard matches.count == 1 else { return nil }
                    return (matches[0].id, matches[0].title)
                }
                guard let left = resolved(leftID, expectedLeft, expectedLeftTitle),
                      let right = resolved(rightID, expectedRight, expectedRightTitle) else {
                    completion(["ok": false, "error": "The requested application did not expose one window"])
                    return
                }
                completion(self.tileResolved(
                    leftID: left.0, rightID: right.0,
                    expectedLeft: expectedLeft, expectedRight: expectedRight,
                    expectedLeftTitle: left.1, expectedRightTitle: right.1
                ))
                return
            }
            let bundle = requested[index].1
            guard let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundle) else {
                completion(["ok": false, "error": "The requested application is not installed"])
                return
            }
            let configuration = NSWorkspace.OpenConfiguration()
            configuration.activates = true
            NSWorkspace.shared.openApplication(at: url, configuration: configuration) { _, error in
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
                    if let error = error {
                        completion(["ok": false, "error": error.localizedDescription])
                    } else {
                        prepare(index + 1)
                    }
                }
            }
        }
        prepare(0)
    }

    func place(id: String, bundleID: String, title: String, placement: String) -> [String: Any] {
        guard ["left", "right", "fill"].contains(placement),
              let window = windows().first(where: {
                  $0.id == id && $0.app.bundleIdentifier == bundleID && $0.title == title
              }) else {
            return ["ok": false, "error": "The selected window is no longer available"]
        }
        if (attribute(window.element, "AXFullScreen") as? Bool) == true {
            window.app.activate()
            guard AXUIElementSetAttributeValue(
                window.element, "AXFullScreen" as CFString, kCFBooleanFalse
            ) == .success else {
                return ["ok": false, "error": "Could not exit native full screen"]
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.8))
        }
        let succeeded = placement == "fill"
            ? fillWithSystemMenu(window.app)
            : tileWithSystemMenu(window.app, side: placement)
        guard succeeded else {
            return ["ok": false, "error": "The app did not accept the window layout command"]
        }
        RunLoop.current.run(until: Date().addingTimeInterval(1.4))
        guard let after = windows().first(where: {
            $0.app.bundleIdentifier == bundleID && $0.title == title
        }), let screen = NSScreen.screens.first(where: {
            $0.frame.contains(after.frame.midpoint)
        }) ?? NSScreen.main else {
            return ["ok": false, "error": "Could not verify the resulting window"]
        }
        let visible = screen.visibleFrame
        let screenTop = NSScreen.screens.first?.frame.maxY ?? screen.frame.maxY
        let expectedX = placement == "right" ? visible.midX : visible.minX
        let expectedWidth = placement == "fill" ? visible.width : visible.width / 2
        let expectedY = screenTop - visible.maxY
        guard abs(after.frame.minX - expectedX) < 45,
              abs(after.frame.minY - expectedY) < 45,
              abs(after.frame.width - expectedWidth) < 55,
              abs(after.frame.height - visible.height) < 55 else {
            return ["ok": false, "error": "The window did not reach the requested layout"]
        }
        return ["ok": true, "summary": "placed \(window.app.localizedName ?? "the window") \(placement)"]
    }

    private func tileResolved(
        leftID: String, rightID: String,
        expectedLeft: String, expectedRight: String,
        expectedLeftTitle: String, expectedRightTitle: String
    ) -> [String: Any] {
        guard leftID != rightID else { return ["ok": false, "error": "Choose two different windows"] }
        let current = windows()
        guard var left = current.first(where: {
                  $0.id == leftID && $0.app.bundleIdentifier == expectedLeft && $0.title == expectedLeftTitle
              }),
              var right = current.first(where: {
                  $0.id == rightID && $0.app.bundleIdentifier == expectedRight && $0.title == expectedRightTitle
              }),
              left.app.processIdentifier != right.app.processIdentifier else {
            return ["ok": false, "error": "One of those windows is no longer available"]
        }
        for window in [left, right] {
            if (attribute(window.element, "AXFullScreen") as? Bool) == true {
                window.app.activate()
                let status = AXUIElementSetAttributeValue(
                    window.element, "AXFullScreen" as CFString, kCFBooleanFalse
                )
                guard status == .success else {
                    return ["ok": false, "error":
                        "Could not exit native full screen for \(window.app.localizedName ?? "an app")"]
                }
                RunLoop.current.run(until: Date().addingTimeInterval(0.8))
            }
        }
        let refreshed = windows()
        if let replacement = refreshed.first(where: {
            $0.app.bundleIdentifier == expectedLeft && $0.title == expectedLeftTitle
        }) { left = replacement }
        if let replacement = refreshed.first(where: {
            $0.app.bundleIdentifier == expectedRight && $0.title == expectedRightTitle
        }) { right = replacement }
        guard (attribute(left.element, "AXFullScreen") as? Bool) != true,
              (attribute(right.element, "AXFullScreen") as? Bool) != true else {
            return ["ok": false, "error": "The apps remained in native full screen"]
        }
        guard let screen = NSScreen.screens.first(where: { $0.frame.contains(left.frame.midpoint) })
            ?? NSScreen.main else {
            return ["ok": false, "error": "No display is available for these windows"]
        }
        // AX uses a top-left global origin; AppKit screen frames use bottom-left.
        let visible = screen.visibleFrame.insetBy(dx: 8, dy: 8)
        let divider: CGFloat = 8
        let half = (visible.width - divider) / 2
        let top = NSScreen.screens.first?.frame.maxY ?? screen.frame.maxY
        let leftPosition = CGPoint(x: visible.minX, y: top - visible.maxY)
        let rightPosition = CGPoint(x: visible.minX + half + divider, y: top - visible.maxY)
        let targetSize = CGSize(width: half, height: visible.height)
        let originalLeft = left.frame
        let originalRight = right.frame
        var leftMenuResult = false
        var rightMenuResult = false
        left.app.unhide()
        right.app.unhide()
        if !placed(left.element, at: leftPosition, size: targetSize) {
            left.app.activate()
            RunLoop.current.run(until: Date().addingTimeInterval(0.15))
            _ = set(left.element, position: leftPosition, size: targetSize)
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
            if !placed(left.element, at: leftPosition, size: targetSize) {
                leftMenuResult = tileWithSystemMenu(left.app, side: "left")
            }
        }
        if !placed(right.element, at: rightPosition, size: targetSize) {
            right.app.activate()
            RunLoop.current.run(until: Date().addingTimeInterval(0.15))
            _ = set(right.element, position: rightPosition, size: targetSize)
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
            if !placed(right.element, at: rightPosition, size: targetSize) {
                rightMenuResult = tileWithSystemMenu(right.app, side: "right")
            }
        }
        RunLoop.current.run(until: Date().addingTimeInterval(rightMenuResult || leftMenuResult ? 1.4 : 0.45))
        let afterMenu = windows()
        if let replacement = afterMenu.first(where: {
            $0.app.bundleIdentifier == expectedLeft && $0.title == expectedLeftTitle
        }) { left = replacement }
        if let replacement = afterMenu.first(where: {
            $0.app.bundleIdentifier == expectedRight && $0.title == expectedRightTitle
        }) { right = replacement }
        guard placed(left.element, at: leftPosition, size: targetSize),
              placed(right.element, at: rightPosition, size: targetSize) else {
            let debug: [String: [CGFloat]] = [
                "left": [point(left.element)?.x ?? -1, point(left.element)?.y ?? -1,
                         size(left.element)?.width ?? -1, size(left.element)?.height ?? -1],
                "right": [point(right.element)?.x ?? -1, point(right.element)?.y ?? -1,
                          size(right.element)?.width ?? -1, size(right.element)?.height ?? -1],
                "expected": [leftPosition.x, leftPosition.y, rightPosition.x,
                             rightPosition.y, half, visible.height],
                "menu_result": [leftMenuResult ? 1 : 0, rightMenuResult ? 1 : 0],
            ]
            _ = set(left.element, position: originalLeft.origin, size: originalLeft.size)
            _ = set(right.element, position: originalRight.origin, size: originalRight.size)
            return [
                "ok": false, "error": "Could not verify the side-by-side layout",
                "debug": debug,
            ]
        }
        left.app.activate()
        return ["ok": true, "summary": "arranged \(left.app.localizedName ?? "left") and \(right.app.localizedName ?? "right") side by side"]
    }
}

private extension CGRect {
    var midpoint: CGPoint { CGPoint(x: midX, y: midY) }
}
