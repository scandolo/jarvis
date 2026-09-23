"""Non-overridable, capability-effect based desktop safety policy."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional


@dataclass(frozen=True)
class SecurityBlock:
    code: str
    reason: str


class SecurityViolation(RuntimeError):
    pass


BLOCKED_EFFECTS = {
    "delete_data": "Deleting or erasing data is disabled",
    "external_communication": "Sending or publishing content is disabled",
    "financial_transaction": "Purchases and money movement are disabled",
    "credential_access": "Credential operations are disabled",
    "security_mutation": "Changing security controls is disabled",
    "code_execution": "Shell and code execution is disabled",
    "power_control": "Shutdown, restart, and logout are disabled",
    "install_software": "Installing or removing software is disabled",
}

ALLOWED_EXECUTORS = {
    "open_bundle", "open_setting", "media_key", "new_note", "go_back",
    "type_text", "share_love", "playful_anger", "share_sadness", "native_select", "arc_search",
    "tile_windows",
    "create_calendar_event",
    "notion_insert",
    "place_window",
}

TERMINAL_APPS = {"terminal", "iterm", "iterm2", "warp", "console", "script editor"}


def inspect_capability(capability: dict, snap: dict) -> Optional[SecurityBlock]:
    for effect in capability.get("effects", ()):
        if effect in BLOCKED_EFFECTS:
            return SecurityBlock(effect, BLOCKED_EFFECTS[effect])

    executor = capability.get("executor") or {}
    executor_type = executor.get("type")
    if executor_type not in ALLOWED_EXECUTORS:
        return SecurityBlock("unknown_executor", "Unknown actions are blocked")

    if executor_type == "type_text":
        front_app = (snap.get("front_app") or "").casefold()
        if front_app in TERMINAL_APPS:
            return SecurityBlock("terminal_input", "Typing into terminal and scripting apps is disabled")
    if executor_type == "arc_search":
        query = executor.get("query")
        if not isinstance(query, str) or not query.strip() or len(query) > 160:
            return SecurityBlock("invalid_search_query", "The search query is invalid")
    if executor_type == "native_select":
        approved_target = (
            (executor.get("kind") == "note_row" and executor.get("app_bundle_id") == "com.apple.Notes")
            or (executor.get("kind") == "arc_tab" and executor.get("app_bundle_id") == "company.thebrowser.Browser")
            or (executor.get("kind") == "calendar_event" and executor.get("app_bundle_id") == "com.apple.iCal")
            or (executor.get("kind") == "google_result" and
                executor.get("app_bundle_id") == "company.thebrowser.Browser" and
                snap.get("page_url") in {"google.com/search", "www.google.com/search"})
        )
        if not approved_target or snap.get("front_bundle_id") != executor.get("app_bundle_id"):
            return SecurityBlock("untrusted_ui_target", "That visible control is not an approved navigation target")
        target = next(
            (item for item in snap.get("elements", []) if item.get("id") == executor.get("target_id")),
            None,
        )
        if target is None or target.get("kind") != executor.get("kind") or target.get("label") != executor.get("label"):
            return SecurityBlock("stale_ui_target", "The selected target is no longer visible")
        if executor.get("kind") == "google_result":
            destination = executor.get("destination")
            if not isinstance(destination, str) or not destination.startswith("https://") or target.get("destination") != destination:
                return SecurityBlock("unsafe_web_target", "That search result is not a verified HTTPS target")
    if executor_type == "tile_windows":
        windows = snap.get("windows", [])
        if executor.get("left_id") == executor.get("right_id"):
            return SecurityBlock("invalid_window_pair", "Two different windows are required")
        for side in ("left", "right"):
            expected = next((window for window in windows if window.get("id") == executor.get(f"{side}_id")), None)
            if expected is None or expected.get("bundle_id") != executor.get(f"{side}_bundle_id") or expected.get("title", "") != executor.get(f"{side}_title"):
                return SecurityBlock("stale_window", "A selected window is no longer available")
        if executor.get("left_bundle_id") == executor.get("right_bundle_id"):
            return SecurityBlock("same_app_windows", "Choose windows from two different apps")
    if executor_type == "place_window":
        target = next((window for window in snap.get("windows", [])
                       if window.get("id") == executor.get("target_id")), None)
        if (executor.get("placement") not in {"left", "right", "fill"} or
            target is None or target.get("will_open") or
            target.get("bundle_id") != executor.get("app_bundle_id") or
            target.get("title") != executor.get("window_title") or
            snap.get("front_bundle_id") != executor.get("app_bundle_id") or
            snap.get("window_title") != executor.get("window_title")):
            return SecurityBlock("stale_window", "The current window is no longer available")
    if executor_type == "create_calendar_event":
        title = executor.get("title")
        start_text = executor.get("start")
        duration = executor.get("duration_minutes")
        if not isinstance(title, str) or not title.strip() or len(title) > 120:
            return SecurityBlock("invalid_event_title", "The event title is invalid")
        if duration not in {30, 60, 90, 120}:
            return SecurityBlock("invalid_event_duration", "The event duration is not supported")
        try:
            start = datetime.fromisoformat(start_text)
            now = datetime.now().astimezone()
            if start.tzinfo is None or not now < start <= now + timedelta(days=91):
                raise ValueError
        except (TypeError, ValueError):
            return SecurityBlock("invalid_event_start", "The event start time is invalid")
    if executor_type == "notion_insert":
        if (snap.get("front_bundle_id") != "notion.id" or
            not snap.get("window_title") or
            snap.get("window_title") != executor.get("window_title") or
            executor.get("block") not in {"database", "text"}):
            return SecurityBlock("untrusted_notion_page", "The requested Notion page is no longer frontmost")
    return None


def enforce(result: dict, snap: dict):
    capability = result.get("capability") or {}
    block = inspect_capability(capability, snap)
    if block:
        raise SecurityViolation(block.reason)
    executor = capability.get("executor") or {}
    if executor.get("type") == "arc_search" and executor.get("query") not in result.get("transcript", ""):
        raise SecurityViolation("The search query was not grounded in the spoken words")
    if executor.get("type") == "create_calendar_event" and executor.get("title") not in result.get("transcript", ""):
        raise SecurityViolation("The event title was not grounded in the spoken words")
