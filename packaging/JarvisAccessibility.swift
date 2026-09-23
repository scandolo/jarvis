import AppKit
import ApplicationServices
import Foundation


/// The signed launcher owns Accessibility. It inventories the front window,
/// while only narrowly scoped navigation targets become executable.
final class JarvisAccessibility {
    private struct CachedTarget {
        let element: AXUIElement
        let bundleID: String
        let label: String
        let kind: String
        let destination: String?
    }

    private var targets: [String: CachedTarget] = [:]

    private func attribute(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
        var value: CFTypeRef?
        let status = AXUIElementCopyAttributeValue(element, name as CFString, &value)
        return status == .success ? value : nil
    }

    private func children(_ element: AXUIElement) -> [AXUIElement] {
        (attribute(element, kAXChildrenAttribute) as? [AXUIElement]) ?? []
    }

    private func stringValue(_ element: AXUIElement, _ name: String) -> String? {
        attribute(element, name) as? String
    }

    private func label(_ element: AXUIElement, role: String) -> String {
        let names = [kAXTitleAttribute, kAXDescriptionAttribute]
        for name in names {
            let value = (stringValue(element, name) ?? "")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            if !value.isEmpty { return String(value.prefix(180)) }
        }
        if role == "AXRow" { return String(textInRow(element).prefix(180)) }
        if role == "AXStaticText" || role == "AXHeading" || role == "AXLink" {
            let value = (stringValue(element, kAXValueAttribute) ?? "")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            return String(value.prefix(180))
        }
        return ""
    }

    private func textInRow(_ element: AXUIElement, depth: Int = 0) -> String {
        if depth > 4 { return "" }
        let role = stringValue(element, kAXRoleAttribute) ?? ""
        if role == "AXStaticText" {
            return (stringValue(element, kAXValueAttribute)
                ?? stringValue(element, kAXTitleAttribute)
                ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        }
        for child in children(element) {
            let text = textInRow(child, depth: depth + 1)
            if !text.isEmpty { return text }
        }
        return ""
    }

    private func hasNoteCell(_ element: AXUIElement, depth: Int = 0) -> Bool {
        if depth > 4 { return false }
        if stringValue(element, kAXIdentifierAttribute) == "ICMNoteListCell" {
            return true
        }
        return children(element).contains { hasNoteCell($0, depth: depth + 1) }
    }

    private func frame(_ element: AXUIElement) -> CGRect? {
        guard
            let rawPosition = attribute(element, kAXPositionAttribute),
            let rawSize = attribute(element, kAXSizeAttribute),
            CFGetTypeID(rawPosition) == AXValueGetTypeID(),
            CFGetTypeID(rawSize) == AXValueGetTypeID()
        else { return nil }
        var point = CGPoint.zero
        var size = CGSize.zero
        guard
            AXValueGetValue(rawPosition as! AXValue, .cgPoint, &point),
            AXValueGetValue(rawSize as! AXValue, .cgSize, &size)
        else { return nil }
        return CGRect(origin: point, size: size)
    }

    private func clickCenter(_ element: AXUIElement) -> Bool {
        guard let bounds = frame(element), bounds.width > 0, bounds.height > 0 else { return false }
        let point = CGPoint(x: bounds.midX, y: bounds.midY)
        guard
            let down = CGEvent(
                mouseEventSource: nil, mouseType: .leftMouseDown,
                mouseCursorPosition: point, mouseButton: .left
            ),
            let up = CGEvent(
                mouseEventSource: nil, mouseType: .leftMouseUp,
                mouseCursorPosition: point, mouseButton: .left
            )
        else { return false }
        down.post(tap: .cghidEventTap)
        up.post(tap: .cghidEventTap)
        return true
    }

    private func destinationURL(_ element: AXUIElement) -> URL? {
        let raw = attribute(element, kAXURLAttribute)
        if let url = raw as? URL, url.scheme == "https", url.host != nil { return url }
        let value = (raw as? String) ?? stringValue(element, kAXValueAttribute)
        guard let value = value, !value.isEmpty else { return nil }
        let candidate = value.contains("://") ? value : "https://" + value
        guard let url = URL(string: candidate), url.scheme == "https", url.host != nil else {
            return nil
        }
        return url
    }

    private func focusedWindow(_ app: NSRunningApplication) -> AXUIElement? {
        let appElement = AXUIElementCreateApplication(app.processIdentifier)
        if let window = attribute(appElement, kAXFocusedWindowAttribute),
           CFGetTypeID(window) == AXUIElementGetTypeID() {
            return (window as! AXUIElement)
        }
        if let windows = attribute(appElement, kAXWindowsAttribute) as? [AXUIElement] {
            return windows.first
        }
        return nil
    }

    private func diagnostics(_ app: NSRunningApplication) -> [String: Any] {
        let appElement = AXUIElementCreateApplication(app.processIdentifier)
        var focused: CFTypeRef?
        var windows: CFTypeRef?
        let focusStatus = AXUIElementCopyAttributeValue(
            appElement, kAXFocusedWindowAttribute as CFString, &focused
        )
        let windowsStatus = AXUIElementCopyAttributeValue(
            appElement, kAXWindowsAttribute as CFString, &windows
        )
        return [
            "pid": app.processIdentifier,
            "focus_status": focusStatus.rawValue,
            "focused_type": focused.map { CFGetTypeID($0) } ?? 0,
            "windows_status": windowsStatus.rawValue,
            "windows_type": windows.map { CFGetTypeID($0) } ?? 0,
            "window_count": (windows as? [AXUIElement])?.count ?? -1,
        ]
    }

    func capture(bundleIDOverride: String? = nil) -> [String: Any] {
        targets.removeAll()
        let selectedApp = bundleIDOverride.flatMap {
            NSRunningApplication.runningApplications(withBundleIdentifier: $0).first
        } ?? NSWorkspace.shared.frontmostApplication
        guard let app = selectedApp else {
            return ["front_app": NSNull(), "front_bundle_id": NSNull(), "elements": [], "source": "native-ax"]
        }
        let bundleID = app.bundleIdentifier ?? ""
        var manualAccessibilityStatus: Int?
        if bundleID == "notion.id" || bundleID == "com.conductor.app" {
            let appElement = AXUIElementCreateApplication(app.processIdentifier)
            let status = AXUIElementSetAttributeValue(
                appElement, "AXManualAccessibility" as CFString, kCFBooleanTrue
            )
            manualAccessibilityStatus = Int(status.rawValue)
            if bundleIDOverride != nil && status == .success {
                RunLoop.current.run(until: Date().addingTimeInterval(0.25))
            }
        }
        var result: [String: Any] = [
            "front_app": app.localizedName ?? "",
            "front_bundle_id": bundleID,
            "elements": [],
            "source": "native-ax",
        ]
        if bundleIDOverride != nil {
            result["diagnostics"] = diagnostics(app)
            if let status = manualAccessibilityStatus {
                result["manual_accessibility_status"] = status
            }
        }
        guard let window = focusedWindow(app) else { return result }
        result["window_title"] = stringValue(window, kAXTitleAttribute) ?? ""
        let windowFrame = frame(window)
        if let bounds = windowFrame {
            result["window_frame"] = [bounds.minX, bounds.minY,
                                      bounds.width, bounds.height]
        }

        var elements: [[String: Any]] = []
        var screenContext: [[String: Any]] = []
        var pageURL: String?
        var inspected = 0
        func walk(
            _ element: AXUIElement, depth: Int,
            inNotesList: Bool, inArcSidebar: Bool, inCalendarDay: Bool
        ) {
            guard depth <= 13, inspected < 650 else { return }
            inspected += 1
            let role = stringValue(element, kAXRoleAttribute) ?? ""
            let identifier = stringValue(element, kAXIdentifierAttribute) ?? ""
            if role == "AXWebArea" && pageURL == nil {
                let rawURL = attribute(element, kAXURLAttribute)
                let url = (rawURL as? URL) ?? (rawURL as? String).flatMap(URL.init(string:))
                if let url = url, let host = url.host {
                    pageURL = String((host + url.path).prefix(180))
                }
            }
            let notesList = inNotesList || (role == "AXTable" && identifier == "ICMNoteListTableView_asList")
            let arcSidebar = inArcSidebar || identifier == "sidebarAllTabList"
            let calendarDay = inCalendarDay || (bundleID == "com.apple.iCal" && role == "AXList")
            let visible: Bool
            if let itemFrame = frame(element), let windowFrame = windowFrame {
                visible = itemFrame.intersects(windowFrame)
            } else {
                visible = true
            }
            let itemLabel = label(element, role: role)
            let contextualRole = [
                "AXButton", "AXLink", "AXTextField", "AXSearchField",
                "AXHeading", "AXRow",
            ].contains(role)
            let shortBrowserText = bundleID == "company.thebrowser.Browser" &&
                role == "AXStaticText" && itemLabel.count <= 120
            if visible && !itemLabel.isEmpty && screenContext.count < 70 &&
                (contextualRole || shortBrowserText) {
                screenContext.append([
                    "id": "context_\(screenContext.count)",
                    "role": role,
                    "label": itemLabel,
                    "identifier": String(identifier.prefix(100)),
                    "enabled": (attribute(element, kAXEnabledAttribute) as? Bool) ?? true,
                    "selected": (attribute(element, kAXSelectedAttribute) as? Bool) ?? false,
                ])
            }
            if bundleID == "com.apple.Notes" && notesList && role == "AXRow" {
                guard hasNoteCell(element) else { return }
                guard visible else { return }
                let noteLabel = textInRow(element)
                if !noteLabel.isEmpty && elements.count < 60 {
                    let targetID = "note_\(elements.count)"
                    let selected = (attribute(element, kAXSelectedAttribute) as? Bool) ?? false
                    elements.append([
                        "id": targetID,
                        "kind": "note_row",
                        "role": role,
                        "label": String(noteLabel.prefix(180)),
                        "selected": selected,
                    ])
                    targets[targetID] = CachedTarget(
                        element: element,
                        bundleID: bundleID,
                        label: String(noteLabel.prefix(180)),
                        kind: "note_row",
                        destination: nil
                    )
                }
                return
            }
            if bundleID == "company.thebrowser.Browser" && arcSidebar &&
                role == "AXRow" && visible && !itemLabel.isEmpty && elements.count < 60 {
                let targetID = "arc_tab_\(elements.count)"
                let selected = (attribute(element, kAXSelectedAttribute) as? Bool) ?? false
                elements.append([
                    "id": targetID,
                    "kind": "arc_tab",
                    "role": role,
                    "label": itemLabel,
                    "selected": selected,
                ])
                targets[targetID] = CachedTarget(
                    element: element, bundleID: bundleID,
                    label: itemLabel, kind: "arc_tab", destination: nil
                )
                return
            }
            if bundleID == "company.thebrowser.Browser" && role == "AXLink" &&
                visible && (pageURL == "google.com/search" || pageURL == "www.google.com/search") &&
                elements.filter({ $0["kind"] as? String == "google_result" }).count < 12,
                let destination = destinationURL(element), let host = destination.host,
                host != "google.com" && !host.hasSuffix(".google.com") &&
                !itemLabel.isEmpty {
                let targetID = "google_result_\(elements.count)"
                let urlString = destination.absoluteString
                elements.append([
                    "id": targetID, "kind": "google_result", "role": role,
                    "label": itemLabel, "destination": urlString,
                ])
                targets[targetID] = CachedTarget(
                    element: element, bundleID: bundleID, label: itemLabel,
                    kind: "google_result", destination: urlString
                )
            }
            if bundleID == "com.apple.iCal" && calendarDay && role == "AXStaticText" &&
                visible && !itemLabel.isEmpty && elements.count < 60 {
                let targetID = "calendar_event_\(elements.count)"
                elements.append([
                    "id": targetID, "kind": "calendar_event", "role": role,
                    "label": itemLabel,
                ])
                targets[targetID] = CachedTarget(
                    element: element, bundleID: bundleID, label: itemLabel,
                    kind: "calendar_event", destination: nil
                )
                if screenContext.count < 70 {
                    screenContext.append([
                        "id": "context_\(screenContext.count)", "role": "AXEvent",
                        "label": itemLabel, "identifier": "", "enabled": true,
                        "selected": (attribute(element, kAXFocusedAttribute) as? Bool) ?? false,
                    ])
                }
            }
            for child in children(element) {
                walk(
                    child, depth: depth + 1, inNotesList: notesList,
                    inArcSidebar: arcSidebar, inCalendarDay: calendarDay
                )
            }
        }
        walk(window, depth: 0, inNotesList: false, inArcSidebar: false, inCalendarDay: false)
        if bundleIDOverride != nil {
            var debug: [[String: Any]] = []
            func traceTree(_ element: AXUIElement, depth: Int) {
                guard debug.count < 80, depth < 7 else { return }
                let regular = children(element)
                let visible = (attribute(element, "AXVisibleChildren") as? [AXUIElement]) ?? []
                debug.append([
                    "role": stringValue(element, kAXRoleAttribute) ?? "",
                    "label": label(element, role: stringValue(element, kAXRoleAttribute) ?? ""),
                    "children": regular.count, "visible_children": visible.count,
                ])
                for child in regular { traceTree(child, depth: depth + 1) }
            }
            traceTree(window, depth: 0)
            result["debug_tree"] = debug
        }
        result["elements"] = elements
        result["screen_context"] = screenContext
        if let pageURL = pageURL { result["page_url"] = pageURL }
        result["inspected_elements"] = inspected
        return result
    }

    func selectTarget(
        id: String, bundleID: String, label: String, kind: String,
        destination: String? = nil
    ) -> [String: Any] {
        // Re-enumerate immediately before acting; IDs from a prior utterance
        // cannot authorize an action after the UI changes.
        let fresh = capture()
        let freshElements = fresh["elements"] as? [[String: Any]] ?? []
        guard
            fresh["front_bundle_id"] as? String == bundleID,
            freshElements.contains(where: {
                $0["id"] as? String == id && $0["label"] as? String == label &&
                $0["kind"] as? String == kind &&
                (destination == nil || $0["destination"] as? String == destination)
            }),
            let target = targets[id],
            target.bundleID == bundleID,
            target.label == label,
            target.kind == kind,
            target.destination == destination,
            (kind == "note_row" && bundleID == "com.apple.Notes") ||
            (kind == "arc_tab" && bundleID == "company.thebrowser.Browser") ||
            (kind == "calendar_event" && bundleID == "com.apple.iCal") ||
            (kind == "google_result" && bundleID == "company.thebrowser.Browser" &&
                (fresh["page_url"] as? String == "google.com/search" ||
                 fresh["page_url"] as? String == "www.google.com/search"))
        else {
            return ["ok": false, "error": "The selected target is no longer visible"]
        }
        guard NSWorkspace.shared.frontmostApplication?.bundleIdentifier == bundleID else {
            return ["ok": false, "error": "The target app is no longer frontmost"]
        }
        if kind == "arc_tab" {
            let pressed = AXUIElementPerformAction(target.element, kAXPressAction as CFString)
            if pressed != .success && !clickCenter(target.element) {
                return ["ok": false, "error": "Arc tab did not accept a press or click (AX status \(pressed.rawValue))"]
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.35))
            let after = capture()
            let rows = after["elements"] as? [[String: Any]] ?? []
            let selected = rows.contains {
                $0["id"] as? String == id && $0["label"] as? String == label &&
                $0["selected"] as? Bool == true
            }
            return selected
                ? ["ok": true, "summary": "switched to \(label)"]
                : ["ok": false, "error": "Arc did not switch to the requested tab"]
        }
        if kind == "google_result" {
            let pressed = AXUIElementPerformAction(target.element, kAXPressAction as CFString)
            if pressed != .success && !clickCenter(target.element) {
                return ["ok": false, "error": "The search result did not accept a press or click"]
            }
            let deadline = Date().addingTimeInterval(2.0)
            repeat {
                RunLoop.current.run(until: Date().addingTimeInterval(0.2))
                let after = capture()
                if let newPage = after["page_url"] as? String,
                   newPage != "google.com/search" && newPage != "www.google.com/search" {
                    return ["ok": true, "summary": "opened search result \(label)"]
                }
            } while Date() < deadline
            return ["ok": false, "error": "Arc did not visibly open that search result"]
        }
        if kind == "calendar_event" {
            let pressed = AXUIElementPerformAction(target.element, kAXPressAction as CFString)
            if pressed != .success && !clickCenter(target.element) {
                return ["ok": false, "error": "The calendar event did not accept a click"]
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
            let appElement = AXUIElementCreateApplication(
                NSWorkspace.shared.frontmostApplication?.processIdentifier ?? 0
            )
            let focusedElement = attribute(appElement, kAXFocusedUIElementAttribute)
            let focused = ((attribute(target.element, kAXFocusedAttribute) as? Bool) ?? false)
                || (focusedElement.map { CFEqual($0, target.element) } ?? false)
            return focused
                ? ["ok": true, "summary": "selected calendar event \(label)"]
                : ["ok": false, "error": "Could not verify the selected calendar event"]
        }
        let status = AXUIElementSetAttributeValue(
            target.element,
            kAXSelectedAttribute as CFString,
            kCFBooleanTrue
        )
        if status != .success {
            let pressed = AXUIElementPerformAction(target.element, kAXPressAction as CFString)
            if pressed != .success {
                return [
                    "ok": false,
                    "error": "The app rejected the selection (AX statuses \(status.rawValue), \(pressed.rawValue))",
                ]
            }
        }
        let selected = (attribute(target.element, kAXSelectedAttribute) as? Bool) ?? false
        if !selected {
            return ["ok": false, "error": "The app did not select the requested row"]
        }
        return ["ok": true, "summary": kind == "arc_tab" ? "switched to \(label)" : "opened \(label)"]
    }

    func verifiedGoogleResult(id: String, label: String, destination: String) -> URL? {
        let fresh = capture()
        guard fresh["front_bundle_id"] as? String == "company.thebrowser.Browser",
              fresh["page_url"] as? String == "google.com/search" ||
                fresh["page_url"] as? String == "www.google.com/search",
              (fresh["elements"] as? [[String: Any]])?.contains(where: {
                  $0["id"] as? String == id && $0["kind"] as? String == "google_result" &&
                  $0["label"] as? String == label &&
                  $0["destination"] as? String == destination
              }) == true,
              NSWorkspace.shared.frontmostApplication?.bundleIdentifier == "company.thebrowser.Browser",
              let url = URL(string: destination), url.scheme == "https", url.host != nil else {
            return nil
        }
        return url
    }
}
