"""macOS permission preflight for the terminal-free app launcher."""
import subprocess


def accessibility_trusted(prompt=False) -> bool:
    try:
        from ApplicationServices import (
            AXIsProcessTrusted,
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )

        if prompt:
            options = {kAXTrustedCheckOptionPrompt: True}
            return bool(AXIsProcessTrustedWithOptions(options))
        return bool(AXIsProcessTrusted())
    except Exception:
        return False


def notify(title: str, message: str):
    script = (
        "on run argv\n"
        "display notification (item 2 of argv) with title (item 1 of argv)\n"
        "end run"
    )
    subprocess.run(
        ["osascript", "-e", script, title, message],
        check=False,
        capture_output=True,
        text=True,
    )
