import AppKit
import CoreGraphics
import Foundation
import ScreenCaptureKit
import Vision


/// OCR fallback for apps whose web content has no Accessibility labels.
/// Pixel data stays in this process; only short visible text and bounds leave it.
final class JarvisVision {
    func permissionGranted() -> Bool { CGPreflightScreenCaptureAccess() }

    func requestPermission() -> Bool { CGRequestScreenCaptureAccess() }

    func captureVisibleText(completion: @escaping ([[String: Any]]) -> Void) {
        guard permissionGranted(), let screen = NSScreen.main else {
            completion([])
            return
        }
        guard #available(macOS 15.2, *) else {
            completion([])
            return
        }
        SCScreenshotManager.captureImage(in: screen.frame) { image, error in
            guard let image = image, error == nil else {
                completion([])
                return
            }
            completion(self.recognize(image: image, screen: screen))
        }
    }

    /// Re-recognize before clicking; a stale OCR coordinate never authorizes input.
    func clickText(
        label: String, near original: CGPoint, inside window: CGRect,
        completion: @escaping (Bool) -> Void
    ) {
        captureVisibleText { items in
            guard let match = items.first(where: { item in
                guard item["label"] as? String == label,
                      let x = item["x"] as? Int, let y = item["y"] as? Int else { return false }
                let point = CGPoint(x: x, y: y)
                return window.insetBy(dx: 8, dy: 8).contains(point)
                    && abs(point.x - original.x) < 24
                    && abs(point.y - original.y) < 24
            }), let x = match["x"] as? Int, let y = match["y"] as? Int else {
                completion(false)
                return
            }
            let point = CGPoint(x: x, y: y)
            guard let down = CGEvent(
                mouseEventSource: nil, mouseType: .leftMouseDown,
                mouseCursorPosition: point, mouseButton: .left
            ), let up = CGEvent(
                mouseEventSource: nil, mouseType: .leftMouseUp,
                mouseCursorPosition: point, mouseButton: .left
            ) else {
                completion(false)
                return
            }
            down.post(tap: .cghidEventTap)
            up.post(tap: .cghidEventTap)
            completion(true)
        }
    }

    private func recognize(image: CGImage, screen: NSScreen) -> [[String: Any]] {
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = true
        request.recognitionLanguages = ["en-US", "it-IT"]
        let handler = VNImageRequestHandler(cgImage: image, options: [:])
        do { try handler.perform([request]) } catch { return [] }
        let top = NSScreen.screens.first?.frame.maxY ?? screen.frame.maxY
        return (request.results ?? []).prefix(90).enumerated().compactMap { index, observation in
            guard let text = observation.topCandidates(1).first?.string,
                  !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
            let box = observation.boundingBox
            let x = screen.frame.minX + box.midX * screen.frame.width
            let y = top - (screen.frame.minY + box.midY * screen.frame.height)
            return [
                "id": "ocr_\(index)",
                "label": String(text.prefix(160)),
                "x": Int(x.rounded()), "y": Int(y.rounded()),
                "source": "screen-ocr",
            ]
        }
    }
}
