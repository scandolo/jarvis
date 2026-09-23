import AppKit
import ApplicationServices
import Foundation


final class JarvisDelegate: NSObject, NSApplicationDelegate {
    private var runtime: Process?
    private var runtimeInput: FileHandle?
    private var runtimeOutput: FileHandle?
    private var logHandle: FileHandle?
    private var hotkeyMonitor: Any?
    private var spaceObserver: NSObjectProtocol?
    private var rightOptionHeld = false
    private var statusPanel: NSPanel?
    private var statusBackground: NSView?
    private var statusDot: NSView?
    private var levelBars: [NSView] = []
    private var titleLabel: NSTextField?
    private var detailLabel: NSTextField?
    private var hideWorkItem: DispatchWorkItem?
    private var permissionTimer: Timer?
    private var outputBuffer = ""
    private let outputQueue = DispatchQueue(label: "app.jarvis.runtime-output")
    private let accessibility = JarvisAccessibility()
    private let windowManager = JarvisWindowManager()
    private let calendar = JarvisCalendar()
    private let vision = JarvisVision()
    private lazy var notion = JarvisNotion(vision: vision)
    private let emotionOverlay = JarvisEmotionOverlay()

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusPanel = makeStatusPanel()
        spaceObserver = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.activeSpaceDidChangeNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            self?.repositionStatusPanel()
            // The notification can arrive before the new full-screen Space
            // has finished animating; raise the panel again after the switch.
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self] in
                self?.repositionStatusPanel()
            }
        }
        do {
            try prepareLog()
        } catch {
            showFatalError("Jarvis could not open its log: \(error.localizedDescription)")
            NSApp.terminate(nil)
            return
        }
        appendNativeLog("[launcher] started; accessibility trusted=\(AXIsProcessTrusted())")
        if let probeIndex = CommandLine.arguments.firstIndex(of: "--arc-search-probe") {
            let query = CommandLine.arguments.indices.contains(probeIndex + 1)
                ? CommandLine.arguments[probeIndex + 1] : "Jarvis voice demo"
            openNativeApplication(
                bundleID: "company.thebrowser.Browser", query: query, requestID: "probe"
            )
            return
        }
        if let probeIndex = CommandLine.arguments.firstIndex(of: "--open-app-probe") {
            let bundleID = CommandLine.arguments.indices.contains(probeIndex + 1)
                ? CommandLine.arguments[probeIndex + 1] : "com.conductor.app"
            openNativeApplication(bundleID: bundleID, query: nil, requestID: "probe")
            return
        }
        if let probeIndex = CommandLine.arguments.firstIndex(of: "--ax-select-target-probe") {
            guard CommandLine.arguments.indices.contains(probeIndex + 2) else {
                appendNativeLog("[ax-select-target-probe] missing bundle or label")
                NSApp.terminate(nil)
                return
            }
            let bundleID = CommandLine.arguments[probeIndex + 1]
            let requestedLabel = CommandLine.arguments[probeIndex + 2]
            NSRunningApplication.runningApplications(withBundleIdentifier: bundleID)
                .first?.activate()
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
            let snapshot = accessibility.capture(bundleIDOverride: bundleID)
            let rows = snapshot["elements"] as? [[String: Any]] ?? []
            if let row = rows.first(where: { $0["label"] as? String == requestedLabel }),
               let targetID = row["id"] as? String,
               let kind = row["kind"] as? String {
                appendNativeLog("[ax-select-target-probe] " + String(describing:
                    accessibility.selectTarget(
                        id: targetID, bundleID: bundleID, label: requestedLabel, kind: kind
                    )
                ))
            } else {
                appendNativeLog("[ax-select-target-probe] target not visible: \(requestedLabel)")
            }
            NSApp.terminate(nil)
            return
        }
        if let selectIndex = CommandLine.arguments.firstIndex(of: "--ax-select-probe") {
            let requestedLabel = CommandLine.arguments.indices.contains(selectIndex + 1)
                ? CommandLine.arguments[selectIndex + 1] : ""
            NSRunningApplication.runningApplications(withBundleIdentifier: "com.apple.Notes")
                .first?.activate()
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
            let snapshot = accessibility.capture(bundleIDOverride: "com.apple.Notes")
            let rows = snapshot["elements"] as? [[String: Any]] ?? []
            if let row = rows.first(where: { $0["label"] as? String == requestedLabel }),
               let targetID = row["id"] as? String {
                let result = accessibility.selectTarget(
                    id: targetID, bundleID: "com.apple.Notes",
                    label: requestedLabel, kind: "note_row"
                )
                appendNativeLog("[ax-select-probe] \(result)")
            } else {
                appendNativeLog("[ax-select-probe] target not visible: \(requestedLabel)")
            }
            NSApp.terminate(nil)
            return
        }
        if let probeIndex = CommandLine.arguments.firstIndex(of: "--ax-probe") {
            let requestedBundle = CommandLine.arguments.indices.contains(probeIndex + 1)
                ? CommandLine.arguments[probeIndex + 1] : nil
            let snapshot = accessibility.capture(bundleIDOverride: requestedBundle)
            if let data = try? JSONSerialization.data(withJSONObject: snapshot),
               let json = String(data: data, encoding: .utf8) {
                appendNativeLog("[ax-probe] " + json)
            }
            NSApp.terminate(nil)
            return
        }
        if CommandLine.arguments.contains("--vision-probe") {
            vision.captureVisibleText { [weak self] items in
                DispatchQueue.main.async {
                    self?.appendNativeLog("[vision-probe] permission=\(self?.vision.permissionGranted() ?? false) text=\(items.prefix(12))")
                    NSApp.terminate(nil)
                }
            }
            return
        }
        if CommandLine.arguments.contains("--windows-probe") {
            if let data = try? JSONSerialization.data(withJSONObject: windowManager.capture()),
               let json = String(data: data, encoding: .utf8) {
                appendNativeLog("[windows-probe] " + json)
            }
            NSApp.terminate(nil)
            return
        }
        if let probeIndex = CommandLine.arguments.firstIndex(of: "--tile-probe"),
           CommandLine.arguments.indices.contains(probeIndex + 2) {
            let leftBundle = CommandLine.arguments[probeIndex + 1]
            let rightBundle = CommandLine.arguments[probeIndex + 2]
            let inventory = windowManager.capture()
            if let left = inventory.first(where: { $0["bundle_id"] as? String == leftBundle }),
               let right = inventory.first(where: { $0["bundle_id"] as? String == rightBundle }),
               let leftID = left["id"] as? String,
               let rightID = right["id"] as? String {
                windowManager.tile(
                    leftID: leftID, rightID: rightID,
                    expectedLeft: leftBundle, expectedRight: rightBundle,
                    expectedLeftTitle: left["title"] as? String ?? "",
                    expectedRightTitle: right["title"] as? String ?? ""
                ) { [weak self] result in
                    DispatchQueue.main.async {
                        self?.appendNativeLog("[tile-probe] \(result)")
                        NSApp.terminate(nil)
                    }
                }
            } else {
                appendNativeLog("[tile-probe] Missing candidates")
                NSApp.terminate(nil)
            }
            return
        }
        if let probeIndex = CommandLine.arguments.firstIndex(of: "--place-probe"),
           CommandLine.arguments.indices.contains(probeIndex + 2) {
            let bundle = CommandLine.arguments[probeIndex + 1]
            let placement = CommandLine.arguments[probeIndex + 2]
            if let window = windowManager.capture().first(where: {
                $0["bundle_id"] as? String == bundle && $0["will_open"] == nil
            }), let id = window["id"] as? String {
                let result = windowManager.place(
                    id: id, bundleID: bundle,
                    title: window["title"] as? String ?? "", placement: placement
                )
                appendNativeLog("[place-probe] \(result)")
            } else {
                appendNativeLog("[place-probe] Window unavailable")
            }
            NSApp.terminate(nil)
            return
        }
        if let previewIndex = CommandLine.arguments.firstIndex(of: "--overlay-preview") {
            let state = CommandLine.arguments.indices.contains(previewIndex + 1)
                ? CommandLine.arguments[previewIndex + 1] : "listening"
            let title = CommandLine.arguments.indices.contains(previewIndex + 2)
                ? CommandLine.arguments[previewIndex + 2] : "Jarvis is listening"
            let detail = CommandLine.arguments.indices.contains(previewIndex + 3)
                ? CommandLine.arguments[previewIndex + 3] : ""
            showState(
                state: state,
                title: title,
                detail: detail,
                duration: nil
            )
            if state == "listening" { updateAudioLevel(0.55) }
            return
        }
        if let moodIndex = CommandLine.arguments.firstIndex(of: "--emotion-preview") {
            let mood = CommandLine.arguments.indices.contains(moodIndex + 1)
                ? CommandLine.arguments[moodIndex + 1] : "love"
            showState(state: mood, title: "Jarvis reacts", detail: "", duration: 4)
            return
        }
        if AXIsProcessTrusted() {
            startJarvis()
        } else {
            showPermissionInstructions()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let monitor = hotkeyMonitor {
            NSEvent.removeMonitor(monitor)
        }
        if let observer = spaceObserver {
            NSWorkspace.shared.notificationCenter.removeObserver(observer)
        }
        hideWorkItem?.cancel()
        permissionTimer?.invalidate()
        statusPanel?.orderOut(nil)
        emotionOverlay.clear()
        runtimeOutput?.readabilityHandler = nil
        runtimeInput?.closeFile()
        if let process = runtime, process.isRunning {
            process.terminate()
            process.waitUntilExit()
        }
        runtimeOutput?.closeFile()
        logHandle?.closeFile()
    }

    private func startJarvis() {
        guard runtime == nil else { return }
        permissionTimer?.invalidate()
        permissionTimer = nil
        appendNativeLog("[launcher] accessibility granted; starting runtime")
        do {
            try startRuntime()
        } catch {
            showFatalError("Jarvis could not start its runtime: \(error.localizedDescription)")
            NSApp.terminate(nil)
            return
        }
        hotkeyMonitor = NSEvent.addGlobalMonitorForEvents(matching: .flagsChanged) {
            [weak self] event in
            self?.handleFlagsChanged(event)
        }
        showState(
            state: "success",
            title: "Jarvis is ready",
            detail: "Hold right Option to speak",
            duration: 2.5
        )
    }

    private func showPermissionInstructions() {
        NSApp.activate(ignoringOtherApps: true)
        let alert = NSAlert()
        alert.messageText = "Jarvis needs Accessibility access"
        alert.informativeText = "In Privacy & Security → Accessibility, turn Jarvis off and back on once. Jarvis will start automatically when access is active."
        alert.alertStyle = .informational
        alert.addButton(withTitle: "Open Settings")
        alert.addButton(withTitle: "Quit")
        let response = alert.runModal()
        if response == .alertFirstButtonReturn {
            showState(
                state: "waiting",
                title: "Waiting for Accessibility access",
                detail: "Turn Jarvis off and back on in System Settings",
                duration: nil
            )
            appendNativeLog("[launcher] user opened Accessibility settings")
            if let url = URL(string: "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_Accessibility") {
                NSWorkspace.shared.open(url)
            }
            permissionTimer = Timer.scheduledTimer(
                withTimeInterval: 0.75,
                repeats: true
            ) { [weak self] timer in
                guard AXIsProcessTrusted() else { return }
                timer.invalidate()
                self?.startJarvis()
            }
        } else {
            appendNativeLog("[launcher] user quit at Accessibility request")
            NSApp.terminate(nil)
        }
    }

    private func showFatalError(_ message: String) {
        NSApp.activate(ignoringOtherApps: true)
        let alert = NSAlert()
        alert.messageText = "Jarvis could not start"
        alert.informativeText = message
        alert.alertStyle = .critical
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    private func prepareLog() throws {
        let logDirectory = NSString(string: "~/Library/Logs/Jarvis").expandingTildeInPath
        let logPath = NSString(string: "~/Library/Logs/Jarvis/jarvis.log").expandingTildeInPath
        try FileManager.default.createDirectory(
            atPath: logDirectory,
            withIntermediateDirectories: true,
            attributes: nil
        )
        if !FileManager.default.fileExists(atPath: logPath) {
            FileManager.default.createFile(atPath: logPath, contents: nil, attributes: nil)
        }
        guard let log = FileHandle(forWritingAtPath: logPath) else {
            throw NSError(
                domain: "JarvisLauncher",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "The runtime log could not be opened."]
            )
        }
        log.seekToEndOfFile()
        logHandle = log
    }

    private func appendNativeLog(_ message: String) {
        guard let data = (message + "\n").data(using: .utf8) else { return }
        do {
            try logHandle?.write(contentsOf: data)
        } catch {
            // Permission guidance must remain usable even if logging fails.
        }
    }

    private func startRuntime() throws {
        let workspace = "/Users/federico/conductor/workspaces/jarvis/providence"
        let inputPipe = Pipe()
        let outputPipe = Pipe()
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.arguments = ["-m", "jarvis.live"]
        process.currentDirectoryURL = URL(fileURLWithPath: workspace)
        var environment = ProcessInfo.processInfo.environment
        environment["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        environment["JARVIS_NATIVE_HOTKEY"] = "1"
        environment["JARVIS_DEVELOPER_MODE"] = environment["JARVIS_DEVELOPER_MODE"] ?? "1"
        process.environment = environment
        process.standardInput = inputPipe
        process.standardOutput = outputPipe
        process.standardError = outputPipe

        let reader = outputPipe.fileHandleForReading
        reader.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty else { return }
            self?.outputQueue.async {
                self?.appendRuntimeOutput(data)
            }
        }
        process.terminationHandler = { [weak self] process in
            DispatchQueue.main.async {
                self?.showState(
                    state: "error",
                    title: "Jarvis stopped",
                    detail: "Runtime exited with status \(process.terminationStatus)",
                    duration: 5
                )
                NSApp.terminate(nil)
            }
        }
        try process.run()
        runtime = process
        runtimeInput = inputPipe.fileHandleForWriting
        runtimeOutput = reader
    }

    private func appendRuntimeOutput(_ data: Data) {
        do {
            try logHandle?.write(contentsOf: data)
        } catch {
            // The UI should continue even if its diagnostic log becomes unwritable.
        }
        outputBuffer += String(decoding: data, as: UTF8.self)
        while let newline = outputBuffer.firstIndex(of: "\n") {
            let line = String(outputBuffer[..<newline])
            outputBuffer.removeSubrange(...newline)
            DispatchQueue.main.async { [weak self] in
                self?.handleRuntimeLine(line)
            }
        }
    }

    private func handleRuntimeLine(_ line: String) {
        if line.hasPrefix("JARVIS_LEVEL ") {
            if let level = Double(line.dropFirst("JARVIS_LEVEL ".count)) {
                updateAudioLevel(level)
            }
            return
        }
        if line.hasPrefix("JARVIS_NATIVE_ACTION ") {
            let json = String(line.dropFirst("JARVIS_NATIVE_ACTION ".count))
            guard
                let data = json.data(using: .utf8),
                let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                let requestID = payload["request_id"] as? String
            else { return }
            if payload["type"] as? String == "open_application",
               let bundleID = payload["bundle_id"] as? String {
                openNativeApplication(bundleID: bundleID, query: nil, requestID: requestID)
                return
            }
            if payload["type"] as? String == "arc_search",
               let query = payload["query"] as? String {
                openNativeApplication(
                    bundleID: "company.thebrowser.Browser", query: query, requestID: requestID
                )
                return
            }
            if payload["type"] as? String == "tile_windows",
               let leftID = payload["left_id"] as? String,
               let rightID = payload["right_id"] as? String,
               let leftBundle = payload["left_bundle_id"] as? String,
               let rightBundle = payload["right_bundle_id"] as? String,
               let leftTitle = payload["left_title"] as? String,
               let rightTitle = payload["right_title"] as? String {
                windowManager.tile(
                    leftID: leftID, rightID: rightID,
                    expectedLeft: leftBundle, expectedRight: rightBundle,
                    expectedLeftTitle: leftTitle, expectedRightTitle: rightTitle
                ) { [weak self] result in
                    DispatchQueue.main.async { self?.sendActionResult(requestID, result) }
                }
                return
            }
            if payload["type"] as? String == "place_window",
               let targetID = payload["target_id"] as? String,
               let bundleID = payload["app_bundle_id"] as? String,
               let title = payload["window_title"] as? String,
               let placement = payload["placement"] as? String {
                sendActionResult(requestID, windowManager.place(
                    id: targetID, bundleID: bundleID,
                    title: title, placement: placement
                ))
                return
            }
            if payload["type"] as? String == "create_calendar_event",
               let title = payload["title"] as? String,
               let start = payload["start"] as? String,
               let duration = payload["duration_minutes"] as? Int {
                calendar.create(title: title, start: start, durationMinutes: duration) {
                    [weak self] result in
                    DispatchQueue.main.async { self?.sendActionResult(requestID, result) }
                }
                return
            }
            if payload["type"] as? String == "notion_insert",
               let block = payload["block"] as? String,
               let title = payload["window_title"] as? String {
                notion.insert(block: block, expectedTitle: title) { [weak self] result in
                    DispatchQueue.main.async { self?.sendActionResult(requestID, result) }
                }
                return
            }
            let response: [String: Any]
            if
                payload["type"] as? String == "native_select",
                let targetID = payload["target_id"] as? String,
                let bundleID = payload["app_bundle_id"] as? String,
                let label = payload["label"] as? String,
                let kind = payload["kind"] as? String
            {
                if kind == "google_result",
                   let destination = payload["destination"] as? String {
                    guard let url = accessibility.verifiedGoogleResult(
                        id: targetID, label: label, destination: destination
                    ) else {
                        sendActionResult(requestID, ["ok": false, "error":
                            "That search result is no longer on the current Google page"])
                        return
                    }
                    openVerifiedURL(url, in: bundleID, requestID: requestID)
                    return
                }
                response = accessibility.selectTarget(
                    id: targetID, bundleID: bundleID, label: label, kind: kind,
                    destination: payload["destination"] as? String
                )
            } else {
                response = ["ok": false, "error": "Unsupported native action"]
            }
            sendActionResult(requestID, response)
            return
        }
        let prefix = "JARVIS_UI "
        guard line.hasPrefix(prefix) else { return }
        let json = String(line.dropFirst(prefix.count))
        guard
            let data = json.data(using: .utf8),
            let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let state = payload["state"] as? String
        else { return }
        let title = payload["title"] as? String ?? ""
        let detail = payload["detail"] as? String ?? ""
        let duration = (payload["duration"] as? NSNumber)?.doubleValue
        showState(state: state, title: title, detail: detail, duration: duration)
    }

    private func sendActionResult(_ requestID: String, _ response: [String: Any]) {
        sendRuntimeJSON(
            ["event": "action_result", "request_id": requestID]
                .merging(response) { _, new in new }
        )
        appendNativeLog("[native-action] \(requestID) \(response)")
        if requestID == "probe" { NSApp.terminate(nil) }
    }

    private func openNativeApplication(bundleID: String, query: String?, requestID: String) {
        guard let appURL = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleID) else {
            sendActionResult(requestID, ["ok": false, "error": "That application is not installed"])
            return
        }
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.activates = true
        let completion: (NSRunningApplication?, Error?) -> Void = { [weak self] app, error in
            DispatchQueue.main.async {
                if let error = error {
                    self?.sendActionResult(requestID, ["ok": false, "error": error.localizedDescription])
                    return
                }
                guard let app = app else {
                    self?.sendActionResult(requestID, ["ok": false, "error": "Application did not open"])
                    return
                }
                app.activate()
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.55) {
                    let focused = NSWorkspace.shared.frontmostApplication?.bundleIdentifier == bundleID
                    let summary = query == nil
                        ? (focused ? "opened \(app.localizedName ?? bundleID)" : "opened \(app.localizedName ?? bundleID); focus may still be changing")
                        : (focused ? "searched in Arc" : "opened the search in Arc; focus may still be changing")
                    self?.sendActionResult(requestID, ["ok": true, "summary": summary, "focused": focused])
                }
            }
        }
        if let query = query {
            guard !query.isEmpty && query.count <= 160 else {
                sendActionResult(requestID, ["ok": false, "error": "Invalid search query"])
                return
            }
            var components = URLComponents(string: "https://www.google.com/search")!
            components.queryItems = [URLQueryItem(name: "q", value: query)]
            guard let url = components.url else {
                sendActionResult(requestID, ["ok": false, "error": "Invalid search URL"])
                return
            }
            NSWorkspace.shared.open(
                [url], withApplicationAt: appURL,
                configuration: configuration, completionHandler: completion
            )
        } else {
            NSWorkspace.shared.openApplication(
                at: appURL, configuration: configuration, completionHandler: completion
            )
        }
    }

    private func openVerifiedURL(_ url: URL, in bundleID: String, requestID: String) {
        guard bundleID == "company.thebrowser.Browser",
              let appURL = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleID) else {
            sendActionResult(requestID, ["ok": false, "error": "Arc is unavailable"])
            return
        }
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.activates = true
        NSWorkspace.shared.open([url], withApplicationAt: appURL, configuration: configuration) {
            [weak self] app, error in
            DispatchQueue.main.async {
                if let error = error {
                    self?.sendActionResult(requestID, ["ok": false, "error": error.localizedDescription])
                } else if let app = app {
                    app.activate()
                    self?.sendActionResult(requestID, ["ok": true, "summary": "opened the selected result in Arc"])
                } else {
                    self?.sendActionResult(requestID, ["ok": false, "error": "Arc did not open the result"])
                }
            }
        }
    }

    private func handleFlagsChanged(_ event: NSEvent) {
        guard event.keyCode == 61 else { return }
        let held = event.modifierFlags.contains(.option)
        guard held != rightOptionHeld else { return }
        rightOptionHeld = held
        if held {
            showState(
                state: "starting",
                title: "Starting microphone…",
                detail: "Hold right Option to speak",
                duration: nil
            )
            sendRuntimeEvent("down\n")
        } else {
            let snapshot = accessibility.capture()
            var context = snapshot
            context["windows"] = windowManager.capture()
            appendNativeLog(
                "[native-snapshot] app=\(snapshot["front_app"] ?? "") elements=\((snapshot["elements"] as? [[String: Any]])?.count ?? 0) windows=\((context["windows"] as? [[String: Any]])?.count ?? 0)"
            )
            func finish(_ completed: [String: Any]) {
                showState(
                    state: "thinking",
                    title: "Jev is thinking…",
                    detail: "Understanding what you meant",
                    duration: nil
                )
                sendRuntimeJSON(["event": "up", "snapshot": completed])
            }
            if snapshot["front_bundle_id"] as? String == "notion.id",
               vision.permissionGranted(),
               let frame = snapshot["window_frame"] as? [CGFloat], frame.count == 4 {
                let bounds = CGRect(x: frame[0], y: frame[1],
                                    width: frame[2], height: frame[3])
                vision.captureVisibleText { [weak self] items in
                    DispatchQueue.main.async {
                        guard let self = self else { return }
                        var enriched = context
                        var existing = (context["screen_context"] as? [[String: Any]]) ?? []
                        for item in items {
                            guard existing.count < 70,
                                  let x = item["x"] as? Int,
                                  let y = item["y"] as? Int,
                                  bounds.contains(CGPoint(x: x, y: y)) else { continue }
                            existing.append([
                                "id": item["id"] ?? "", "role": "OCRText",
                                "label": item["label"] ?? "", "x": x, "y": y,
                            ])
                        }
                        enriched["screen_context"] = existing
                        self.appendNativeLog("[native-ocr] app=Notion visible_text=\(existing.count)")
                        finish(enriched)
                    }
                }
            } else {
                finish(context)
            }
        }
    }

    private func sendRuntimeJSON(_ value: [String: Any]) {
        guard
            let data = try? JSONSerialization.data(withJSONObject: value),
            let line = String(data: data, encoding: .utf8)
        else { return }
        sendRuntimeEvent(line + "\n")
    }

    private func sendRuntimeEvent(_ event: String) {
        guard let data = event.data(using: .utf8) else { return }
        do {
            try runtimeInput?.write(contentsOf: data)
        } catch {
            showFatalError("The voice runtime stopped unexpectedly.")
            NSApp.terminate(nil)
        }
    }

    private func color(for state: String) -> NSColor {
        switch state {
        case "listening": return NSColor.systemGreen
        case "starting": return NSColor.systemOrange
        case "thinking", "executing": return NSColor.systemBlue
        case "waiting", "confirmation", "clarify": return NSColor.systemOrange
        case "success", "love": return NSColor.systemPink
        case "anger": return NSColor.systemOrange
        case "sad": return NSColor.systemBlue
        case "blocked", "error", "no_speech": return NSColor.systemRed
        default: return NSColor.systemGray
        }
    }

    private func showState(
        state: String,
        title: String,
        detail: String,
        duration: Double? = nil
    ) {
        hideWorkItem?.cancel()
        hideWorkItem = nil
        if ["love", "anger", "sad"].contains(state) {
            emotionOverlay.show(state)
            appendNativeLog("[emotion-overlay] mood=\(state) screens=\(NSScreen.screens.count)")
        }
        if state == "idle" || duration == 0 {
            statusPanel?.orderOut(nil)
            return
        }
        let listening = state == "listening" || state == "starting"
        layoutStatusPanel(title: title, detail: listening ? "" : detail, listening: listening)
        titleLabel?.stringValue = title
        detailLabel?.stringValue = detail
        detailLabel?.isHidden = listening || detail.isEmpty
        statusDot?.layer?.backgroundColor = color(for: state).cgColor
        let barColor = state == "listening"
            ? NSColor(calibratedRed: 0.45, green: 0.96, blue: 0.69, alpha: 1)
            : NSColor.white.withAlphaComponent(0.9)
        levelBars.forEach {
            $0.layer?.backgroundColor = barColor.cgColor
            $0.isHidden = !listening
        }
        if state != "listening" {
            updateAudioLevel(0)
        }

        repositionStatusPanel(state: state)

        if let seconds = duration, seconds > 0 {
            let work = DispatchWorkItem { [weak self] in
                self?.statusPanel?.orderOut(nil)
            }
            hideWorkItem = work
            DispatchQueue.main.asyncAfter(deadline: .now() + seconds, execute: work)
        }
    }

    private func updateAudioLevel(_ raw: Double) {
        let level = min(1, max(0, raw))
        let panelWidth = statusPanel?.contentView?.bounds.width ?? 274
        let panelHeight = statusPanel?.contentView?.bounds.height ?? 42
        for (index, bar) in levelBars.enumerated() {
            let variation = [0.75, 1.0, 0.62, 0.9, 0.72][index]
            let height = CGFloat(4 + 20 * level * variation)
            bar.frame = NSRect(
                x: panelWidth - 49 + CGFloat(index * 8),
                y: (panelHeight - height) / 2,
                width: 3,
                height: height
            )
        }
    }

    private func layoutStatusPanel(title: String, detail: String, listening: Bool) {
        let hasDetail = !detail.isEmpty
        let titleFont = NSFont.systemFont(ofSize: 14, weight: .semibold)
        let detailFont = NSFont.systemFont(ofSize: 12, weight: .regular)
        let titleWidth = (title as NSString).size(withAttributes: [.font: titleFont]).width
        let detailWidth = (detail as NSString).size(withAttributes: [.font: detailFont]).width
        let minimumWidth: CGFloat = listening || hasDetail ? 274 : 210
        let availableWidth = (NSScreen.screens.map { $0.frame.width }.min() ?? 600) - 40
        let width = min(max(minimumWidth, ceil(max(titleWidth, detailWidth) + 61)),
                        min(520, availableWidth))
        let height: CGFloat = hasDetail ? 58 : 42
        statusPanel?.setContentSize(NSSize(width: width, height: height))
        statusBackground?.frame = NSRect(x: 0, y: 0, width: width, height: height)
        statusBackground?.layer?.cornerRadius = height / 2
        statusDot?.frame = NSRect(x: 17, y: (height - 10) / 2, width: 10, height: 10)
        statusDot?.layer?.cornerRadius = 5
        let textWidth = width - (listening ? 102 : 61)
        titleLabel?.frame = NSRect(x: 41, y: hasDetail ? 31 : 10,
                                   width: textWidth, height: hasDetail ? 18 : 22)
        titleLabel?.font = titleFont
        detailLabel?.frame = NSRect(x: 41, y: 10, width: width - 61, height: 17)
        detailLabel?.font = detailFont
        updateAudioLevel(0)
    }

    private func repositionStatusPanel(state: String = "space_changed") {
        guard let panel = statusPanel, panel.isVisible || state != "space_changed" else { return }
        let pointer = NSEvent.mouseLocation
        let activeScreen = NSScreen.screens.first { $0.frame.contains(pointer) } ?? NSScreen.main
        guard let screen = activeScreen else { return }
        let area = screen.visibleFrame
        let origin = NSPoint(
            x: area.midX - panel.frame.width / 2,
            y: area.minY + 22
        )
        panel.setFrameOrigin(origin)
        panel.level = .screenSaver
        panel.orderFrontRegardless()
        appendNativeLog(
            "[overlay] state=\(state) visible=\(panel.isVisible) active_space=\(panel.isOnActiveSpace) frame=\(panel.frame) screen=\(screen.localizedName) front_app=\(NSWorkspace.shared.frontmostApplication?.localizedName ?? "unknown")"
        )
    }

    private func makeStatusPanel() -> NSPanel {
        let width: CGFloat = 274
        let height: CGFloat = 42
        let panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: width, height: height),
            styleMask: [.titled, .fullSizeContentView, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        panel.titleVisibility = .hidden
        panel.titlebarAppearsTransparent = true
        panel.standardWindowButton(.closeButton)?.isHidden = true
        panel.standardWindowButton(.miniaturizeButton)?.isHidden = true
        panel.standardWindowButton(.zoomButton)?.isHidden = true
        panel.level = .screenSaver
        panel.isFloatingPanel = true
        panel.hidesOnDeactivate = false
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.ignoresMouseEvents = true
        if #available(macOS 26.0, *) {
            panel.collectionBehavior = [.canJoinAllSpaces, .canJoinAllApplications, .fullScreenAuxiliary, .stationary]
        } else {
            panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        }

        // A near-opaque HUD has reliable contrast over both light and dark
        // content, including wallpaper and full-screen apps.
        let background = NSView(frame: panel.contentView!.bounds)
        background.autoresizingMask = [.width, .height]
        background.wantsLayer = true
        background.layer?.backgroundColor = NSColor(
            calibratedRed: 0.065, green: 0.075, blue: 0.095, alpha: 0.97
        ).cgColor
        background.layer?.cornerRadius = 21
        background.layer?.masksToBounds = true
        background.layer?.borderWidth = 0.5
        background.layer?.borderColor = NSColor.white.withAlphaComponent(0.28).cgColor
        panel.contentView?.addSubview(background)
        statusBackground = background

        let dot = NSView(frame: NSRect(x: 17, y: 16, width: 10, height: 10))
        dot.wantsLayer = true
        dot.layer?.cornerRadius = 5
        dot.layer?.backgroundColor = NSColor.systemGreen.cgColor
        background.addSubview(dot)
        statusDot = dot

        for index in 0..<5 {
            let bar = NSView(frame: NSRect(x: 225 + index * 8, y: 19, width: 3, height: 4))
            bar.wantsLayer = true
            bar.layer?.cornerRadius = 1.5
            bar.layer?.backgroundColor = NSColor.white.withAlphaComponent(0.9).cgColor
            background.addSubview(bar)
            levelBars.append(bar)
        }

        let title = NSTextField(labelWithString: "")
        title.frame = NSRect(x: 41, y: 10, width: width - 102, height: 22)
        title.textColor = .white
        title.font = NSFont.systemFont(ofSize: 14, weight: .semibold)
        title.lineBreakMode = .byTruncatingTail
        background.addSubview(title)
        titleLabel = title

        let detail = NSTextField(labelWithString: "")
        detail.frame = NSRect(x: 41, y: 10, width: width - 61, height: 17)
        detail.textColor = NSColor.white.withAlphaComponent(0.85)
        detail.font = NSFont.systemFont(ofSize: 12, weight: .regular)
        detail.lineBreakMode = .byTruncatingTail
        background.addSubview(detail)
        detailLabel = detail

        return panel
    }
}


@main
enum JarvisMain {
    static func main() {
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        let delegate = JarvisDelegate()
        app.delegate = delegate
        app.run()
    }
}
