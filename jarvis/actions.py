"""Execute one locally constructed, security-checked capability."""
import os

from . import actuate
from .security import enforce
from .native import bridge


def execute(result: dict, snap: dict) -> str:
    enforce(result, snap)
    capability = result.get("capability") or {}
    executor = capability.get("executor") or {}
    executor_type = executor.get("type")

    if executor_type == "open_bundle":
        if os.getenv("JARVIS_NATIVE_HOTKEY") == "1":
            response = bridge.request(
                {"type": "open_application", "bundle_id": executor["bundle_id"]}, timeout=12
            )
            return response.get("summary") or f"opened {executor['name']}"
        else:
            actuate.open_bundle(executor["bundle_id"])
        return f"opened {executor['name']}"
    if executor_type == "arc_search":
        if os.getenv("JARVIS_NATIVE_HOTKEY") == "1":
            response = bridge.request(
                {"type": "arc_search", "query": executor["query"]}, timeout=12
            )
            return response.get("summary") or f"searched Arc for {executor['query']}"
        else:
            actuate.arc_search(executor["query"])
        return f"searched Arc for {executor['query']}"
    if executor_type == "open_setting":
        actuate.open_setting(executor["pane_id"])
        return f"opened {executor['name']} settings"
    if executor_type == "media_key":
        return actuate.media_key(executor["key"])
    if executor_type == "native_select":
        # Notes' large AX tree can take longer than the bridge's 6s default;
        # the old timeout reported failure even when native selection succeeded.
        response = bridge.request(executor, timeout=20)
        return response.get("summary") or f"opened {executor['label']}"
    if executor_type == "tile_windows":
        response = bridge.request(executor, timeout=12)
        return response.get("summary") or "arranged the two windows"
    if executor_type == "place_window":
        response = bridge.request(executor, timeout=12)
        return response.get("summary") or "arranged the current window"
    if executor_type == "create_calendar_event":
        response = bridge.request(executor, timeout=45)
        return response.get("summary") or "created the calendar event"
    if executor_type == "notion_insert":
        response = bridge.request(executor, timeout=30)
        return response.get("summary") or "inserted the Notion block"
    if executor_type == "new_note":
        actuate.new_note()
        return "created a new note"
    if executor_type == "go_back":
        actuate.go_back()
        return "went back"
    if executor_type == "type_text":
        actuate.type_text(executor["text"])
        return "typed the selected text"
    if executor_type == "share_love":
        return "shared some love"
    if executor_type == "playful_anger":
        return "reacted playfully"
    if executor_type == "share_sadness":
        return "shared sympathy"
    raise actuate.ActuationError("No supported action was selected")
