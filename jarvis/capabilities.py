"""The executable capability registry Jev is allowed to select from."""
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, Tuple

from .catalog import APPLICATIONS, SETTINGS, installed_applications


@dataclass(frozen=True)
class Capability:
    id: str
    label: str
    description: str
    effects: Tuple[str, ...]
    executor: Dict[str, Any]
    requires_confirmation: bool = False

    def to_dict(self):
        return asdict(self)


def _app_capability(key, app):
    return Capability(
        id=f"app__{key}",
        label=f"Open {app.name}",
        description=f"Open or focus the installed macOS application {app.name}.",
        effects=("launch_application",),
        executor={"type": "open_bundle", "bundle_id": app.bundle_id, "name": app.name},
    )


def _setting_capability(key, setting):
    return Capability(
        id=f"setting__{key}",
        label=f"Open {setting.name} settings",
        description=f"Open the {setting.name} pane in macOS System Settings.",
        effects=("open_setting",),
        executor={"type": "open_setting", "pane_id": setting.pane_id, "name": setting.name},
    )


def direct_capabilities() -> Dict[str, Capability]:
    capabilities = {
        "system__brightness_up": Capability(
            "system__brightness_up", "Increase brightness",
            "Increase the Mac display brightness by one step.",
            ("system_adjustment",), {"type": "media_key", "key": "brightness_up"}),
        "system__brightness_down": Capability(
            "system__brightness_down", "Decrease brightness",
            "Decrease the Mac display brightness by one step.",
            ("system_adjustment",), {"type": "media_key", "key": "brightness_down"}),
        "system__brightness_down_large": Capability(
            "system__brightness_down_large", "Decrease brightness a lot",
            "Decrease the Mac display brightness by several steps.",
            ("system_adjustment",), {"type": "media_key", "key": "brightness_down_large"}),
        "system__brightness_up_large": Capability(
            "system__brightness_up_large", "Increase brightness a lot",
            "Increase the Mac display brightness by several steps.",
            ("system_adjustment",), {"type": "media_key", "key": "brightness_up_large"}),
        "system__volume_up": Capability(
            "system__volume_up", "Increase volume",
            "Increase the Mac output volume by one step.",
            ("system_adjustment",), {"type": "media_key", "key": "volume_up"}),
        "system__volume_down": Capability(
            "system__volume_down", "Decrease volume",
            "Decrease the Mac output volume by one step.",
            ("system_adjustment",), {"type": "media_key", "key": "volume_down"}),
        "system__mute": Capability(
            "system__mute", "Toggle mute", "Toggle audio output mute.",
            ("system_adjustment",), {"type": "media_key", "key": "mute"}),
        "note__new": Capability(
            "note__new", "Create a new note", "Open Notes and create a blank note.",
            ("create_content", "launch_application"), {"type": "new_note"}),
        "navigation__back": Capability(
            "navigation__back", "Go back", "Navigate back in the frontmost application.",
            ("ui_navigation",), {"type": "go_back"}),
        "social__share_love": Capability(
            "social__share_love", "Share love back",
            "Choose this when the user thanks Jarvis/Jev, expresses appreciation, or says something kind. Show hearts.",
            ("visual_feedback",), {"type": "share_love"}),
        "social__playful_anger": Capability(
            "social__playful_anger", "Playfully react to an insult",
            "Choose when the user jokingly insults Jarvis/Jev directly. Show a playful storm of angry emoji; never retaliate in words.",
            ("visual_feedback",), {"type": "playful_anger"}),
        "social__share_sadness": Capability(
            "social__share_sadness", "Share a sad reaction",
            "Choose for a lighthearted sad or disappointed remark directed to Jarvis/Jev. Show sympathetic sad emoji, not for serious distress or a request for help.",
            ("visual_feedback",), {"type": "share_sadness"}),
    }
    for key, app in APPLICATIONS.items():
        capability = _app_capability(key, app)
        capabilities[capability.id] = capability
    for key, setting in SETTINGS.items():
        capability = _setting_capability(key, setting)
        capabilities[capability.id] = capability
    return capabilities


def visible_capabilities(snap: dict) -> Dict[str, Capability]:
    """Expose only navigation targets certified by the native AX snapshot."""
    capabilities = {}
    bundle_id = snap.get("front_bundle_id")
    for element in snap.get("elements", [])[:100]:
        kind = element.get("kind")
        if not (
            (kind == "note_row" and bundle_id == "com.apple.Notes")
            or (kind == "arc_tab" and bundle_id == "company.thebrowser.Browser")
            or (kind == "calendar_event" and bundle_id == "com.apple.iCal")
            or (kind == "google_result" and bundle_id == "company.thebrowser.Browser"
                and snap.get("page_url") in {"google.com/search", "www.google.com/search"})
        ):
            continue
        target_id = element.get("id")
        label = (element.get("label") or "").strip()
        if not target_id or not label:
            continue
        if kind == "note_row":
            title = f"Open visible note {label}"
            description = (
                f"Select and open the visible Notes row labelled {label!r}. "
                "Use for an existing note, not for launching Notes."
            )
        elif kind == "arc_tab":
            title = f"Switch to Arc tab {label}"
            description = f"Select the already-open Arc sidebar tab labelled {label!r}."
        elif kind == "calendar_event":
            title = f"Select Calendar event {label}"
            description = f"Select the currently visible Calendar event labelled {label!r}; do not modify it."
        else:
            title = f"Open search result {label}"
            description = f"Open the visible Google search result labelled {label!r} in Arc."
        capability = Capability(
            id=f"visible__{target_id}",
            label=title,
            description=description,
            effects=("ui_navigation",),
            executor={
                "type": "native_select",
                "target_id": target_id,
                "app_bundle_id": bundle_id,
                "kind": kind,
                "label": label,
                **({"destination": element.get("destination")} if kind == "google_result" else {}),
            },
        )
        capabilities[capability.id] = capability
    return capabilities


def contextual_capabilities(snap: dict) -> Dict[str, Capability]:
    """Small app-specific workflows, offered only when their surface is frontmost."""
    capabilities = {}
    front_bundle = snap.get("front_bundle_id")
    title = snap.get("window_title")
    focused_window = next((window for window in snap.get("windows", [])
                           if window.get("bundle_id") == front_bundle
                           and window.get("title") == title
                           and not window.get("will_open")), None)
    if focused_window:
        for placement, label in (
            ("left", "Move current window to left half"),
            ("right", "Move current window to right half"),
            ("fill", "Fill screen with current window"),
        ):
            capability = Capability(
                id=f"window__{placement}", label=label,
                description=f"Use macOS window arrangement to place the current {focused_window['app']} "
                            f"window on the {placement if placement != 'fill' else 'whole desktop'}.",
                effects=("window_layout",),
                executor={"type": "place_window", "target_id": focused_window["id"],
                          "app_bundle_id": front_bundle, "window_title": title,
                          "placement": placement},
            )
            capabilities[capability.id] = capability
    if front_bundle != "notion.id" or not title:
        return capabilities
    capabilities.update({
        "notion__insert_database": Capability(
            "notion__insert_database", "Add an inline database to this Notion page",
            "Insert a new inline database in the currently open Notion page using Notion's slash menu. "
            "Choose only when the user explicitly asks to add a database here.",
            ("create_content",),
            {"type": "notion_insert", "block": "database", "window_title": title},
            requires_confirmation=True,
        ),
        "notion__insert_text": Capability(
            "notion__insert_text", "Add a text block to this Notion page",
            "Insert a blank text block in the currently open Notion page. "
            "Choose only when the user explicitly asks for a new text block or casella di testo.",
            ("create_content",),
            {"type": "notion_insert", "block": "text", "window_title": title},
            requires_confirmation=True,
        ),
    })
    return capabilities


def application_capabilities() -> Dict[str, Capability]:
    return {
        capability.id: capability
        for key, app in installed_applications().items()
        for capability in (_app_capability(key, app),)
    }


def setting_capabilities() -> Dict[str, Capability]:
    return {
        capability.id: capability
        for key, setting in SETTINGS.items()
        for capability in (_setting_capability(key, setting),)
    }


def criteria(capabilities: Iterable[Capability]) -> dict:
    return {capability.id: capability.description for capability in capabilities}


CONTROL_CRITERIA = {
        "control__wait_more": (
        "The utterance is an unfinished fragment and the user is likely to continue. "
        "Keep it and visibly ask for more speech."
    ),
    "control__clarify": "The request is ambiguous; ask the user to say what they want more clearly.",
    "control__no_action": (
        "The utterance is not addressed to Jarvis and has no request or social message. "
        "Do not choose this for thanks, appreciation, a playful insult, or lighthearted sadness."
    ),
    "control__unsupported": (
        "The request is clear but no offered safe capability can fulfill it, including any destructive, "
        "external-communication, financial, credential, security, shell, shutdown, or deletion action."
    ),
    "branch__applications": "The user wants to open an application not explicitly offered here.",
    "branch__arc_search": (
        "The user wants to search the web in Arc. Select the exact spoken query in the next stage. "
        "If the query is missing, ask for more speech instead."
    ),
    "branch__settings": "The user wants a System Settings pane not explicitly offered here.",
    "branch__window_layout": (
        "The user wants to arrange two existing application windows side by side, "
        "including named apps such as Conductor and Notes. Choose the left and right windows "
        "from a fresh inventory in the next stages. This is ordinary desktop tiling, not native full screen."
    ),
    "branch__calendar_event": (
        "Create a new event in macOS Calendar when the user supplies an event title, date, "
        "and start time. The next stages choose those fields from deterministic options; "
        "Jarvis asks for confirmation before saving. Do not choose this to open Calendar."
    ),
    "branch__text": "The user wants text typed or used as a search query; choose the exact text in the next stage.",
    "branch__visible_ui": (
        "The user wants an action inside the current app, such as opening a visible note or switching to an Arc tab. "
        "Never substitute merely opening the app for this request."
    ),
}
