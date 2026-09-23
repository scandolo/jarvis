"""Small, truthful desktop snapshot.

Until Accessibility element extraction is implemented, return no UI targets
rather than invented Notes controls. Known applications and settings come from
the deterministic command catalog instead.
"""
import shutil

from .devlog import trace


def _front_app():
    try:
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return app.localizedName() if app is not None else None
    except Exception:
        return None

def snapshot() -> dict:
    result = {"front_app": _front_app(), "elements": [], "source": "front-app-only"}
    trace("perception.snapshot", snapshot=result)
    return result

def has_deps() -> bool:
    return shutil.which("cliclick") is not None
