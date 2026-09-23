import AppKit
import ApplicationServices
import Foundation


/// A tightly scoped Notion slash-command workflow, grounded in a fresh empty editor.
final class JarvisNotion {
    private let vision: JarvisVision

    init(vision: JarvisVision) { self.vision = vision }

    private func attribute(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
        var value: CFTypeRef?
        return AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success
            ? value : nil
    }

    private func focusedPage(expectedTitle: String) -> CGRect? {
        guard let app = NSWorkspace.shared.frontmostApplication,
              app.bundleIdentifier == "notion.id" else { return nil }
        let axApp = AXUIElementCreateApplication(app.processIdentifier)
        guard let rawWindow = attribute(axApp, kAXFocusedWindowAttribute),
              CFGetTypeID(rawWindow) == AXUIElementGetTypeID() else { return nil }
        let window = rawWindow as! AXUIElement
        guard attribute(window, kAXTitleAttribute) as? String == expectedTitle,
              let rawPosition = attribute(window, kAXPositionAttribute),
              let rawSize = attribute(window, kAXSizeAttribute),
              CFGetTypeID(rawPosition) == AXValueGetTypeID(),
              CFGetTypeID(rawSize) == AXValueGetTypeID() else { return nil }
        var position = CGPoint.zero
        var size = CGSize.zero
        guard AXValueGetValue(rawPosition as! AXValue, .cgPoint, &position),
              AXValueGetValue(rawSize as! AXValue, .cgSize, &size) else { return nil }
        return CGRect(origin: position, size: size)
    }

    private func press(_ key: CGKeyCode, command: Bool = false) {
        guard let down = CGEvent(keyboardEventSource: nil, virtualKey: key, keyDown: true),
              let up = CGEvent(keyboardEventSource: nil, virtualKey: key, keyDown: false) else {
            return
        }
        if command {
            down.flags = .maskCommand
            up.flags = .maskCommand
        }
        down.post(tap: .cghidEventTap)
        up.post(tap: .cghidEventTap)
    }

    private func type(_ string: String) {
        for character in string.utf16 {
            var unit = character
            guard let down = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: true),
                  let up = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: false) else {
                return
            }
            down.keyboardSetUnicodeString(stringLength: 1, unicodeString: &unit)
            up.keyboardSetUnicodeString(stringLength: 1, unicodeString: &unit)
            down.post(tap: .cghidEventTap)
            up.post(tap: .cghidEventTap)
        }
    }

    func insert(
        block: String, expectedTitle: String,
        completion: @escaping ([String: Any]) -> Void
    ) {
        guard ["database", "text"].contains(block),
              let window = focusedPage(expectedTitle: expectedTitle) else {
            completion(["ok": false, "error": "The requested Notion page is no longer frontmost"])
            return
        }
        guard vision.permissionGranted() else {
            _ = vision.requestPermission()
            completion(["ok": false, "error":
                "Grant Jarvis Screen Recording, then restart"])
            return
        }
        vision.captureVisibleText { [weak self] items in
            DispatchQueue.main.async {
                guard let self = self,
                      self.focusedPage(expectedTitle: expectedTitle) != nil,
                      items.contains(where: { $0["label"] as? String == expectedTitle }),
                      let anchor = items.first(where: { item in
                          guard let label = item["label"] as? String,
                                let x = item["x"] as? Int,
                                let y = item["y"] as? Int else { return false }
                          let value = label.lowercased()
                          let emptyEditor = value.contains("write, press")
                              || value.contains("type '/' for commands")
                              || value.contains("type / for commands")
                          return emptyEditor && window.insetBy(dx: 12, dy: 12)
                              .contains(CGPoint(x: x, y: y))
                      }), let label = anchor["label"] as? String,
                      let x = anchor["x"] as? Int,
                      let y = anchor["y"] as? Int else {
                    completion(["ok": false, "error":
                        "Open an empty block in this Notion page and try again; no click was made"])
                    return
                }
                self.vision.clickText(
                    label: label, near: CGPoint(x: x, y: y), inside: window
                ) { clicked in
                    DispatchQueue.main.async {
                        guard clicked, self.focusedPage(expectedTitle: expectedTitle) != nil else {
                            completion(["ok": false, "error":
                                "The Notion page changed before the click; nothing was inserted"])
                            return
                        }
                        self.type(block == "database" ? "/database" : "/text")
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.45) {
                            self.checkSlashMenu(block: block, title: expectedTitle, completion: completion)
                        }
                    }
                }
            }
        }
    }

    private func checkSlashMenu(
        block: String, title: String,
        completion: @escaping ([String: Any]) -> Void
    ) {
        guard focusedPage(expectedTitle: title) != nil else {
            completion(["ok": false, "error": "Notion lost focus before the slash menu opened"])
            return
        }
        vision.captureVisibleText { [weak self] items in
            DispatchQueue.main.async {
                guard let self = self,
                      self.focusedPage(expectedTitle: title) != nil,
                      items.contains(where: {
                          let label = ($0["label"] as? String ?? "")
                              .trimmingCharacters(in: .whitespacesAndNewlines)
                          if block == "database" {
                              return label.caseInsensitiveCompare("Database") == .orderedSame
                                  || label.localizedCaseInsensitiveContains("Database - Inline")
                          }
                          return label.caseInsensitiveCompare("Text") == .orderedSame
                              || label.caseInsensitiveCompare("Plain text") == .orderedSame
                      }) else {
                    completion(["ok": false, "error":
                        "Notion did not expose the expected slash command; check the current page"])
                    return
                }
                self.press(36) // choose the top slash-menu result
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.45) {
                    self.verifyInsertion(block: block, title: title, completion: completion)
                }
            }
        }
    }

    private func verifyInsertion(
        block: String, title: String,
        completion: @escaping ([String: Any]) -> Void
    ) {
        guard focusedPage(expectedTitle: title) != nil else {
            completion(["ok": false, "error": "Notion changed pages before verification"])
            return
        }
        vision.captureVisibleText { items in
            DispatchQueue.main.async {
            let labels = items.compactMap { $0["label"] as? String }
            if block == "database" {
                if let choice = items.first(where: {
                    ($0["label"] as? String ?? "").localizedCaseInsensitiveContains("new empty database")
                }), let x = choice["x"] as? Int, let y = choice["y"] as? Int,
                   let label = choice["label"] as? String,
                   let window = self.focusedPage(expectedTitle: title) {
                    self.vision.clickText(
                        label: label, near: CGPoint(x: x, y: y), inside: window
                    ) { clicked in
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.7) {
                            guard clicked, self.focusedPage(expectedTitle: title) != nil else {
                                completion(["ok": false, "error":
                                    "Could not verify the database setup choice"])
                                return
                            }
                            self.confirmDatabase(title: title, completion: completion)
                        }
                    }
                    return
                }
                self.confirmDatabase(title: title, labels: labels, completion: completion)
            } else {
                let menuStillOpen = labels.contains { $0 == "/text" }
                completion(menuStillOpen
                    ? ["ok": false, "error": "Notion did not finish inserting the text block"]
                    : ["ok": true, "summary": "added a text block to \(title)"])
            }
            }
        }
    }

    private func confirmDatabase(
        title: String, labels: [String]? = nil,
        completion: @escaping ([String: Any]) -> Void
    ) {
        if let labels = labels {
            let inserted = labels.contains {
                $0.localizedCaseInsensitiveContains("new database")
                    || $0.localizedCaseInsensitiveContains("untitled database")
            }
            completion(inserted
                ? ["ok": true, "summary": "added a database to \(title)"]
                : ["ok": false, "error":
                    "The database command ran, but Jarvis could not verify a new database"])
            return
        }
        vision.captureVisibleText { items in
            self.confirmDatabase(
                title: title, labels: items.compactMap { $0["label"] as? String },
                completion: completion
            )
        }
    }
}
