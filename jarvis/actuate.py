"""Small, checked macOS actuation primitives. No shell interpolation."""
import subprocess
import shutil
import ctypes
import time
from urllib.parse import urlencode

class ActuationError(RuntimeError):
    pass


def _run(argv):
    try:
        subprocess.run(argv, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise ActuationError(f"Required command is not installed: {argv[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "unknown error").strip()
        raise ActuationError(f"{argv[0]} failed: {detail}") from exc


def open_app(name: str):
    if not name.strip():
        raise ActuationError("No application name was selected")
    _run(["open", "-a", name.strip()])


def open_bundle(bundle_id: str):
    if not bundle_id.strip():
        raise ActuationError("No application bundle was selected")
    _run(["open", "-b", bundle_id.strip()])
    try:
        from AppKit import NSRunningApplication, NSWorkspace, NSApplicationActivateIgnoringOtherApps
    except ImportError:
        return
    deadline = time.monotonic() + 2.5
    while time.monotonic() < deadline:
        candidates = NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id)
        if candidates:
            candidates[0].activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        front = NSWorkspace.sharedWorkspace().frontmostApplication()
        if front is not None and front.bundleIdentifier() == bundle_id:
            return
        time.sleep(0.1)
    raise ActuationError(f"{bundle_id} opened but could not be brought to the front")


def open_setting(pane_id: str):
    _run(["open", f"x-apple.systempreferences:{pane_id}"])


def arc_search(query: str):
    url = "https://www.google.com/search?" + urlencode({"q": query})
    _run(["open", "-b", "company.thebrowser.Browser", url])


def _display_services():
    """Current macOS display service; fail explicitly when unavailable."""
    try:
        graphics = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        display = ctypes.CDLL(
            "/System/Library/PrivateFrameworks/DisplayServices.framework/DisplayServices"
        )
    except OSError as exc:
        raise ActuationError("Display brightness control is unavailable on this Mac") from exc
    graphics.CGMainDisplayID.restype = ctypes.c_uint32
    display.DisplayServicesGetBrightness.argtypes = [
        ctypes.c_uint32, ctypes.POINTER(ctypes.c_float)
    ]
    display.DisplayServicesGetBrightness.restype = ctypes.c_int32
    display.DisplayServicesSetBrightness.argtypes = [ctypes.c_uint32, ctypes.c_float]
    display.DisplayServicesSetBrightness.restype = ctypes.c_int32
    return graphics.CGMainDisplayID(), display


def _brightness_get(display_id, service):
    value = ctypes.c_float()
    status = service.DisplayServicesGetBrightness(display_id, ctypes.byref(value))
    if status != 0:
        raise ActuationError(f"Could not read display brightness (status {status})")
    return value.value


def adjust_brightness(direction: int, amount: float = 0.0625):
    display_id, service = _display_services()
    before = _brightness_get(display_id, service)
    target = min(1.0, max(0.02, before + direction * amount))
    if abs(target - before) < 0.001:
        return f"brightness already at {'maximum' if direction > 0 else 'minimum'}"
    status = service.DisplayServicesSetBrightness(display_id, ctypes.c_float(target))
    if status != 0:
        raise ActuationError(f"Could not set display brightness (status {status})")
    after = _brightness_get(display_id, service)
    if (after - before) * direction < 0.005:
        raise ActuationError(
            f"Brightness did not move in the requested direction ({before:.2f} → {after:.2f})"
        )
    return f"brightness {round(after * 100)}%"


def _osascript_value(expression: str) -> str:
    try:
        result = subprocess.run(
            ["osascript", "-e", expression],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise ActuationError(f"Could not read or set audio output: {exc}") from exc
    return result.stdout.strip()


def adjust_volume(direction: int, amount: int = 6):
    before = int(_osascript_value("output volume of (get volume settings)"))
    target = max(0, min(100, before + direction * amount))
    if target == before:
        return f"volume already at {'maximum' if direction > 0 else 'minimum'}"
    _osascript_value(f"set volume output volume {target}")
    after = int(_osascript_value("output volume of (get volume settings)"))
    if (after - before) * direction <= 0:
        raise ActuationError(
            f"Volume did not move in the requested direction ({before} → {after})"
        )
    return f"volume {after}%"


def media_key(key: str):
    if key == "brightness_up":
        return adjust_brightness(+1)
    if key == "brightness_down":
        return adjust_brightness(-1)
    if key == "brightness_up_large":
        return adjust_brightness(+1, 0.25)
    if key == "brightness_down_large":
        return adjust_brightness(-1, 0.25)
    if key == "volume_up":
        return adjust_volume(+1)
    if key == "volume_down":
        return adjust_volume(-1)
    if key == "mute":
        before = _osascript_value("output muted of (get volume settings)").lower() == "true"
        _osascript_value(f"set volume with output muted" if not before else "set volume without output muted")
        after = _osascript_value("output muted of (get volume settings)").lower() == "true"
        if after == before:
            raise ActuationError("Mute state did not change")
        return "muted" if after else "unmuted"
    raise ActuationError("Unknown media control")


def click(x: int, y: int):
    _run([_cliclick(), f"c:{int(x)},{int(y)}"])

def type_text(text: str):
    # candidate-span text only (from transcript, picked by Jev) — never generated
    if text:
        _run([_cliclick(), f"t:{text}"])


def _cliclick():
    command = shutil.which("cliclick")
    if command:
        return command
    homebrew = "/opt/homebrew/bin/cliclick"
    if shutil.which(homebrew):
        return homebrew
    raise ActuationError("cliclick is not installed")


def new_note():
    open_app("Notes")
    _run(["osascript", "-e", 'tell application "System Events" to keystroke "n" using command down'])


def go_back():
    _run(["osascript", "-e", 'tell application "System Events" to key code 123 using command down'])
