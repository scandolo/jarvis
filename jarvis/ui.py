"""UI state messages sent from the Python runtime to the native launcher."""
import json
import os

from .devlog import trace


NATIVE = os.getenv("JARVIS_NATIVE_HOTKEY") == "1"


def emit(state: str, title: str, detail: str = "", duration=None):
    payload = {
        "state": state,
        "title": title,
        "detail": detail,
        "duration": duration,
    }
    trace("ui.state", **payload)
    if NATIVE:
        print("JARVIS_UI " + json.dumps(payload, ensure_ascii=False), flush=True)
