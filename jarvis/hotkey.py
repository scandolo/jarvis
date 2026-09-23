"""Right-Option push-to-talk hotkey via pynput."""
import sys
import threading
import json

from .native import bridge

class Hotkey:
    def __init__(self, on_down, on_up):
        from pynput import keyboard

        self._keyboard = keyboard
        self.on_down, self.on_up = on_down, on_up
        self._held = False
        self.listener = self._keyboard.Listener(on_press=self._press, on_release=self._rel)

    def _is_ropt(self, key) -> bool:
        # ONLY right-option. Previously also matched cmd_r / vk 61, which is
        # why Command triggered listening. alt_r == right Option on macOS.
        try:
            return key == self._keyboard.Key.alt_r
        except Exception:
            return False

    def _press(self, key):
        if not self._held and self._is_ropt(key):
            self._held = True
            self.on_down()

    def _rel(self, key):
        if self._held and self._is_ropt(key):
            self._held = False
            self.on_up()

    def start(self):
        self.listener.start()

    def stop(self):
        self.listener.stop()


class StdinHotkey:
    """Receive native launcher hotkey events without requesting Python access."""

    def __init__(self, on_down, on_up):
        self.on_down = on_down
        self.on_up = on_up
        self._held = False
        self._stopped = False
        self._thread = None

    def _run(self):
        for line in sys.stdin:
            if self._stopped:
                return
            raw = line.strip()
            if raw.startswith("{"):
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if payload.get("event") == "action_result":
                    bridge.receive(payload)
                    continue
                event = payload.get("event")
            else:
                payload = {}
                event = raw.lower()
            if event == "down" and not self._held:
                self._held = True
                self.on_down()
            elif event == "up" and self._held:
                self._held = False
                self.on_up(payload.get("snapshot"))

    def start(self):
        self._thread = threading.Thread(
            target=self._run,
            name="JarvisNativeHotkey",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stopped = True
