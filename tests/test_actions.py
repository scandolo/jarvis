import pytest

from jarvis import actions
from jarvis.catalog import installed_applications


def _capability(executor, effects=("launch_application",), label="Do it"):
    return {
        "action": "execute",
        "transcript": "spoken words are not parsed locally",
        "capability": {
            "id": "test",
            "label": label,
            "effects": effects,
            "executor": executor,
            "requires_confirmation": False,
        },
    }


def test_installed_catalog_contains_main_apps():
    apps = installed_applications()
    assert apps["arc"].name == "Arc"
    assert apps["conductor"].name == "Conductor"
    assert apps["chatgpt"].name == "ChatGPT"
    assert len(apps) > 20


def test_execute_opens_capability_bundle(monkeypatch):
    opened = []
    monkeypatch.setattr(actions.actuate, "open_bundle", opened.append)
    result = _capability({
        "type": "open_bundle",
        "bundle_id": "com.apple.Notes",
        "name": "Notes",
    })
    assert actions.execute(result, {"elements": []}) == "opened Notes"
    assert opened == ["com.apple.Notes"]


@pytest.mark.parametrize("key", ["brightness_up", "brightness_down", "volume_down"])
def test_media_adjustments_are_explicit_safe_actions(monkeypatch, key):
    pressed = []
    monkeypatch.setattr(
        actions.actuate, "media_key",
        lambda value: pressed.append(value) or "verified adjustment"
    )
    result = _capability(
        {"type": "media_key", "key": key},
        effects=("system_adjustment",),
        label="Adjust control",
    )
    assert actions.execute(result, {}) == "verified adjustment"
    assert pressed == [key]


def test_execute_rejects_unknown_executor():
    result = _capability({"type": "delete_everything"}, effects=("delete_data",))
    with pytest.raises(Exception, match="Deleting"):
        actions.execute(result, {})


def test_arc_search_uses_grounded_query(monkeypatch):
    searched = []
    monkeypatch.setattr(actions.actuate, "arc_search", searched.append)
    result = _capability(
        {"type": "arc_search", "query": "pasta"},
        effects=("web_navigation",),
    )
    result["transcript"] = "search pasta"
    assert actions.execute(result, {}) == "searched Arc for pasta"
    assert searched == ["pasta"]


def test_native_launcher_reports_app_focus_without_python_timeout(monkeypatch):
    monkeypatch.setenv("JARVIS_NATIVE_HOTKEY", "1")
    requests = []
    monkeypatch.setattr(
        actions.bridge, "request",
        lambda action, timeout: requests.append((action, timeout)) or {
            "ok": True, "summary": "opened Arc",
        },
    )
    result = _capability({
        "type": "open_bundle", "bundle_id": "company.thebrowser.Browser", "name": "Arc",
    })
    assert actions.execute(result, {}) == "opened Arc"
    assert requests[0][0]["type"] == "open_application"
