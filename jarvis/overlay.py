"""Bottom-center native macOS listening indicator."""
import multiprocessing
import signal


def _overlay_worker(connection):
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        from AppKit import (
            NSApplication,
            NSApplicationActivationPolicyAccessory,
            NSBackingStoreBuffered,
            NSColor,
            NSFont,
            NSFontWeightSemibold,
            NSMakeRect,
            NSPanel,
            NSScreen,
            NSStatusWindowLevel,
            NSTextAlignmentCenter,
            NSTextField,
            NSWindowCollectionBehaviorCanJoinAllSpaces,
            NSWindowCollectionBehaviorFullScreenAuxiliary,
            NSWindowStyleMaskBorderless,
        )
        from Foundation import NSDate, NSRunLoop

        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        app.finishLaunching()

        width, height = 250, 46
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, width, height),
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(NSStatusWindowLevel)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.08, 0.94))
        panel.setHasShadow_(True)
        panel.setIgnoresMouseEvents_(True)
        panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )

        label = NSTextField.labelWithString_("●  Jarvis is listening")
        label.setFrame_(NSMakeRect(0, 0, width, height))
        label.setAlignment_(NSTextAlignmentCenter)
        label.setTextColor_(NSColor.whiteColor())
        label.setFont_(NSFont.systemFontOfSize_weight_(15, NSFontWeightSemibold))
        panel.contentView().addSubview_(label)

        screen = NSScreen.mainScreen().visibleFrame()
        x = screen.origin.x + (screen.size.width - width) / 2
        y = screen.origin.y + 24
        panel.setFrame_display_(NSMakeRect(x, y, width, height), True)
        connection.send(("ready", None))

        running = True
        while running:
            while connection.poll():
                command = connection.recv()
                if command == "show":
                    panel.orderFrontRegardless()
                elif command == "hide":
                    panel.orderOut_(None)
                elif command == "quit":
                    running = False
                    break
            NSRunLoop.currentRunLoop().runUntilDate_(
                NSDate.dateWithTimeIntervalSinceNow_(0.04)
            )
        panel.orderOut_(None)
    except Exception as exc:
        try:
            connection.send(("error", f"{type(exc).__name__}: {exc}"))
        except Exception:
            pass
    finally:
        connection.close()


class ListeningOverlay:
    """Own the UI helper process; degrade to no-op if Cocoa is unavailable."""

    def __init__(self, startup_timeout=3):
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        self._connection = parent
        self._process = context.Process(
            target=_overlay_worker,
            args=(child,),
            name="JarvisOverlay",
            daemon=True,
        )
        self._process.start()
        child.close()
        self.error = None
        if parent.poll(startup_timeout):
            status, detail = parent.recv()
            if status == "ready":
                return
            self.error = detail or "overlay failed to initialize"
        else:
            self.error = "overlay timed out during initialization"
        self.close()

    @property
    def available(self):
        return self.error is None and self._process.is_alive()

    def _send(self, command):
        if not self.available:
            return
        try:
            self._connection.send(command)
        except (BrokenPipeError, EOFError, OSError):
            self.error = "overlay process stopped"

    def show(self):
        self._send("show")

    def hide(self):
        self._send("hide")

    def close(self):
        process = getattr(self, "_process", None)
        connection = getattr(self, "_connection", None)
        if process is None:
            return
        if process.is_alive() and connection is not None:
            try:
                connection.send("quit")
            except (BrokenPipeError, EOFError, OSError):
                pass
            process.join(timeout=1)
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)
        if connection is not None:
            connection.close()
