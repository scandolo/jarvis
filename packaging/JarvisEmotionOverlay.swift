import AppKit
import Foundation


/// A click-through, short-lived reaction across every display.
final class JarvisEmotionOverlay {
    private var panels: [NSPanel] = []
    private var generation = 0

    func show(_ mood: String) {
        clear()
        generation += 1
        let currentGeneration = generation
        let symbols: [String]
        switch mood {
        case "love": symbols = ["❤️", "💜", "💙", "💚", "💛", "💖", "💕"]
        case "anger": symbols = ["😤", "😠", "😡", "💢", "🔥"]
        case "sad": symbols = ["😢", "🥺", "💧", "💙", "😔"]
        default: return
        }

        for screen in NSScreen.screens {
            let panel = NSPanel(
                contentRect: screen.frame,
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
            panel.hasShadow = false
            panel.ignoresMouseEvents = true
            if #available(macOS 26.0, *) {
                panel.collectionBehavior = [.canJoinAllSpaces, .canJoinAllApplications, .fullScreenAuxiliary, .stationary]
            } else {
                panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
            }
            guard let canvas = panel.contentView else { continue }
            let count = max(70, Int(screen.frame.width * screen.frame.height / 13_000))
            for _ in 0..<count {
                let symbol = symbols.randomElement()!
                let size = CGFloat(Int.random(in: 28...58))
                let x = CGFloat.random(in: 0...max(1, screen.frame.width - size))
                let y = CGFloat.random(in: 0...max(1, screen.frame.height - size))
                let label = NSTextField(labelWithString: symbol)
                label.font = NSFont.systemFont(ofSize: size)
                label.alignment = .center
                label.frame = NSRect(x: x, y: y, width: size + 8, height: size + 8)
                label.alphaValue = CGFloat.random(in: 0.72...1.0)
                canvas.addSubview(label)
                let drift = CGFloat.random(in: -220 ... -80)
                NSAnimationContext.runAnimationGroup { context in
                    context.duration = Double.random(in: 2.8...4.1)
                    context.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
                    label.animator().setFrameOrigin(NSPoint(x: x, y: y + drift))
                    label.animator().alphaValue = 0.08
                }
            }
            panel.orderFrontRegardless()
            panels.append(panel)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 4.2) { [weak self] in
            guard self?.generation == currentGeneration else { return }
            self?.clear()
        }
    }

    func clear() {
        for panel in panels { panel.orderOut(nil) }
        panels.removeAll()
    }
}
