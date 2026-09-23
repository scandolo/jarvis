import pytest

from jarvis.security import SecurityViolation, enforce, inspect_capability


@pytest.mark.parametrize("effect", [
    "delete_data",
    "external_communication",
    "financial_transaction",
    "credential_access",
    "security_mutation",
    "code_execution",
    "power_control",
    "install_software",
])
def test_disruptive_effects_are_hard_blocked(effect):
    capability = {"effects": [effect], "executor": {"type": "open_bundle"}}
    assert inspect_capability(capability, {}) is not None


@pytest.mark.parametrize("key", ["brightness_up", "brightness_down", "volume_down"])
def test_system_adjustments_are_not_risky(key):
    capability = {
        "effects": ["system_adjustment"],
        "executor": {"type": "media_key", "key": key},
    }
    assert inspect_capability(capability, {}) is None


def test_unknown_executor_is_blocked_at_actuation_boundary():
    result = {
        "capability": {
            "effects": ["ui_navigation"],
            "executor": {"type": "invented_by_model"},
        }
    }
    with pytest.raises(SecurityViolation, match="Unknown"):
        enforce(result, {})


def test_terminal_typing_is_blocked():
    result = {
        "capability": {
            "effects": ["type_text"],
            "executor": {"type": "type_text", "text": "hello"},
        }
    }
    with pytest.raises(SecurityViolation, match="terminal"):
        enforce(result, {"front_app": "Terminal"})


def test_visible_note_target_must_match_native_snapshot():
    capability = {
        "effects": ["ui_navigation"],
        "executor": {
            "type": "native_select",
            "kind": "note_row",
            "app_bundle_id": "com.apple.Notes",
            "target_id": "note_0",
            "label": "BOOKMARKS LIBRI",
        },
    }
    snapshot = {
        "front_bundle_id": "com.apple.Notes",
        "elements": [{"id": "note_0", "kind": "note_row", "label": "BOOKMARKS LIBRI"}],
    }
    assert inspect_capability(capability, snapshot) is None
    snapshot["elements"][0]["label"] = "Something else"
    assert inspect_capability(capability, snapshot).code == "stale_ui_target"


def test_arc_tab_target_must_match_native_snapshot():
    capability = {
        "effects": ["ui_navigation"],
        "executor": {
            "type": "native_select", "kind": "arc_tab",
            "app_bundle_id": "company.thebrowser.Browser",
            "target_id": "arc_tab_0", "label": "Dashboard",
        },
    }
    snapshot = {
        "front_bundle_id": "company.thebrowser.Browser",
        "elements": [{"id": "arc_tab_0", "kind": "arc_tab", "label": "Dashboard"}],
    }
    assert inspect_capability(capability, snapshot) is None
    snapshot["front_bundle_id"] = "com.apple.finder"
    assert inspect_capability(capability, snapshot).code == "untrusted_ui_target"


def test_calendar_event_target_must_match_native_snapshot():
    capability = {"effects": ["ui_navigation"], "executor": {
        "type": "native_select", "kind": "calendar_event",
        "app_bundle_id": "com.apple.iCal", "target_id": "calendar_event_0",
        "label": "Compleanno Anna",
    }}
    snap = {"front_bundle_id": "com.apple.iCal", "elements": [
        {"id": "calendar_event_0", "kind": "calendar_event", "label": "Compleanno Anna"},
    ]}
    assert inspect_capability(capability, snap) is None
    snap["elements"] = []
    assert inspect_capability(capability, snap).code == "stale_ui_target"


def test_arc_search_query_must_come_from_transcript():
    capability = {"effects": ["web_navigation"], "executor": {"type": "arc_search", "query": "pasta"}}
    with pytest.raises(SecurityViolation, match="grounded"):
        enforce({"capability": capability, "transcript": "search shoes"}, {})


def test_google_result_requires_current_search_page_and_exact_destination():
    capability = {
        "effects": ["web_navigation"],
        "executor": {
            "type": "native_select", "kind": "google_result",
            "app_bundle_id": "company.thebrowser.Browser", "target_id": "google_result_0",
            "label": "Example", "destination": "https://example.com/",
        },
    }
    snapshot = {
        "front_bundle_id": "company.thebrowser.Browser", "page_url": "google.com/search",
        "elements": [{
            "id": "google_result_0", "kind": "google_result", "label": "Example",
            "destination": "https://example.com/",
        }],
    }
    assert inspect_capability(capability, snapshot) is None
    snapshot["page_url"] = "example.com/"
    assert inspect_capability(capability, snapshot) is not None


def test_window_layout_requires_exact_inventory():
    capability = {"effects": ["window_layout"], "executor": {
        "type": "tile_windows", "left_id": "window_1_0", "right_id": "window_2_0",
        "left_bundle_id": "com.conductor.app", "right_bundle_id": "com.apple.Notes",
        "left_title": "Jarvis", "right_title": "Notes",
    }}
    snap = {"windows": [
        {"id": "window_1_0", "bundle_id": "com.conductor.app", "title": "Jarvis"},
        {"id": "window_2_0", "bundle_id": "com.apple.Notes", "title": "Notes"},
    ]}
    assert inspect_capability(capability, snap) is None
    snap["windows"][1]["title"] = "Another note"
    assert inspect_capability(capability, snap).code == "stale_window"


def test_current_window_placement_requires_fresh_focus():
    capability = {"effects": ["window_layout"], "executor": {
        "type": "place_window", "target_id": "window_1_0",
        "app_bundle_id": "com.apple.Notes", "window_title": "Notes",
        "placement": "left",
    }}
    snap = {"front_bundle_id": "com.apple.Notes", "window_title": "Notes",
            "windows": [{"id": "window_1_0", "bundle_id": "com.apple.Notes",
                         "title": "Notes"}]}
    assert inspect_capability(capability, snap) is None
    snap["front_bundle_id"] = "com.apple.iCal"
    assert inspect_capability(capability, snap).code == "stale_window"


def test_calendar_event_rejects_unspoken_title_and_past_time():
    from datetime import datetime, timedelta
    future = (datetime.now().astimezone() + timedelta(days=1)).isoformat()
    capability = {"effects": ["create_content"], "executor": {
        "type": "create_calendar_event", "title": "pranzo con Luca",
        "start": future, "duration_minutes": 60,
    }}
    assert inspect_capability(capability, {}) is None
    with pytest.raises(SecurityViolation, match="grounded"):
        enforce({"capability": capability, "transcript": "crea cena con Luca"}, {})
    capability["executor"]["start"] = (datetime.now().astimezone() - timedelta(days=1)).isoformat()
    assert inspect_capability(capability, {}).code == "invalid_event_start"


def test_notion_insert_requires_same_frontmost_page_and_allowlisted_block():
    capability = {"effects": ["create_content"], "executor": {
        "type": "notion_insert", "block": "database", "window_title": "Project plan"
    }}
    snap = {"front_bundle_id": "notion.id", "window_title": "Project plan"}
    assert inspect_capability(capability, snap) is None
    capability["executor"]["block"] = "delete"
    assert inspect_capability(capability, snap).code == "untrusted_notion_page"
