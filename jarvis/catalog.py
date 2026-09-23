"""Deterministic discovery of applications and System Settings panes.

This module never interprets a transcript. It only describes things that are
actually available for Jev to choose from.
"""
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import os
from pathlib import Path
import plistlib
import unicodedata
from typing import Dict


@dataclass(frozen=True)
class Application:
    name: str
    bundle_id: str
    path: str = ""


@dataclass(frozen=True)
class Setting:
    name: str
    pane_id: str


# Common applications are promoted into the first Jev decision. Discovery
# below adds everything else installed on the machine to the app branch.
APPLICATIONS: Dict[str, Application] = {
    "arc": Application("Arc", "company.thebrowser.Browser"),
    "chatgpt": Application("ChatGPT", "com.openai.codex"),
    "claude": Application("Claude", "com.anthropic.claudefordesktop"),
    "conductor": Application("Conductor", "com.conductor.app"),
    "chrome": Application("Google Chrome", "com.google.Chrome"),
    "safari": Application("Safari", "com.apple.Safari"),
    "notion": Application("Notion", "notion.id"),
    "notion_calendar": Application("Notion Calendar", "com.cron.electron"),
    "calendar": Application("Calendar", "com.apple.iCal"),
    "notes": Application("Notes", "com.apple.Notes"),
    "mail": Application("Mail", "com.apple.mail"),
    "messages": Application("Messages", "com.apple.MobileSMS"),
    "finder": Application("Finder", "com.apple.finder"),
    "reminders": Application("Reminders", "com.apple.reminders"),
    "terminal": Application("Terminal", "com.apple.Terminal"),
    "settings": Application("System Settings", "com.apple.systempreferences"),
    "music": Application("Music", "com.apple.Music"),
    "maps": Application("Maps", "com.apple.Maps"),
    "photos": Application("Photos", "com.apple.Photos"),
    "preview": Application("Preview", "com.apple.Preview"),
    "passwords": Application("Passwords", "com.apple.Passwords"),
    "calculator": Application("Calculator", "com.apple.calculator"),
}


SETTINGS: Dict[str, Setting] = {
    "wifi": Setting("Wi-Fi", "com.apple.wifi-settings-extension"),
    "bluetooth": Setting("Bluetooth", "com.apple.BluetoothSettings"),
    "displays": Setting("Displays", "com.apple.Displays-Settings.extension"),
    "sound": Setting("Sound", "com.apple.Sound-Settings.extension"),
    "notifications": Setting("Notifications", "com.apple.Notifications-Settings.extension"),
    "privacy": Setting("Privacy & Security", "com.apple.settings.PrivacySecurity.extension"),
    "keyboard": Setting("Keyboard", "com.apple.Keyboard-Settings.extension"),
    "trackpad": Setting("Trackpad", "com.apple.Trackpad-Settings.extension"),
    "mouse": Setting("Mouse", "com.apple.Mouse-Settings.extension"),
    "accessibility": Setting("Accessibility", "com.apple.Accessibility-Settings.extension"),
    "appearance": Setting("Appearance", "com.apple.Appearance-Settings.extension"),
    "control_center": Setting("Control Center", "com.apple.ControlCenter-Settings.extension"),
    "accounts": Setting("Internet Accounts", "com.apple.Internet-Accounts-Settings.extension"),
    "users": Setting("Users & Groups", "com.apple.Users-Groups-Settings.extension"),
    "battery": Setting("Battery", "com.apple.Battery-Settings.extension"),
    "wallpaper": Setting("Wallpaper", "com.apple.Wallpaper-Settings.extension"),
    "screen_saver": Setting("Screen Saver", "com.apple.ScreenSaver-Settings.extension"),
    "lock_screen": Setting("Lock Screen", "com.apple.Lock-Screen-Settings.extension"),
    "general": Setting("General", "com.apple.systempreferences.GeneralSettings"),
}


def _identifier(name: str, bundle_id: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    pieces = []
    previous_separator = False
    for character in ascii_name.lower():
        if character.isalnum():
            pieces.append(character)
            previous_separator = False
        elif not previous_separator:
            pieces.append("_")
            previous_separator = True
    slug = "".join(pieces).strip("_") or "application"
    digest = hashlib.sha1(bundle_id.encode("utf-8")).hexdigest()[:8]
    return f"{slug}_{digest}"


def _candidate_apps(root: Path, depth: int = 2):
    if not root.exists():
        return
    root_parts = len(root.parts)
    for directory, names, _ in os.walk(root):
        current = Path(directory)
        current_depth = len(current.parts) - root_parts
        entries = list(names)
        names[:] = [
            name for name in names
            if not name.startswith(".") and not name.endswith(".app") and current_depth < depth
        ]
        for name in entries:
            if name.endswith(".app"):
                yield current / name


def _read_application(path: Path):
    info_path = path / "Contents" / "Info.plist"
    try:
        with info_path.open("rb") as handle:
            info = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException):
        return None
    if info.get("LSBackgroundOnly") or info.get("LSUIElement"):
        return None
    bundle_id = str(info.get("CFBundleIdentifier") or "").strip()
    if not bundle_id:
        return None
    name = str(
        info.get("CFBundleDisplayName")
        or info.get("CFBundleName")
        or path.stem
    ).strip()
    return Application(name=name, bundle_id=bundle_id, path=str(path))


@lru_cache(maxsize=1)
def installed_applications() -> Dict[str, Application]:
    """Return a stable, de-duplicated inventory of user-facing Mac apps."""
    applications = dict(APPLICATIONS)
    known_bundles = {app.bundle_id: key for key, app in applications.items()}
    roots = (
        Path("/Applications"),
        Path.home() / "Applications",
        Path("/System/Applications"),
        Path("/System/Applications/Utilities"),
    )
    for root in roots:
        for path in _candidate_apps(root):
            app = _read_application(path)
            if app is None:
                continue
            existing = known_bundles.get(app.bundle_id)
            if existing is not None:
                old = applications[existing]
                applications[existing] = Application(old.name, old.bundle_id, app.path)
                continue
            key = _identifier(app.name, app.bundle_id)
            while key in applications:
                key += "_"
            applications[key] = app
            known_bundles[app.bundle_id] = key
    return dict(sorted(applications.items(), key=lambda item: item[1].name.casefold()))


def application_criteria(applications=None) -> dict:
    entries = applications or installed_applications()
    return {key: f"Open or focus {app.name}" for key, app in entries.items()}


def setting_criteria() -> dict:
    return {key: f"Open the {setting.name} pane in System Settings" for key, setting in SETTINGS.items()}
