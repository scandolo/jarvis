#!/bin/zsh
set -eu

SCRIPT_DIR="${0:A:h}"
SOURCE_APP="$SCRIPT_DIR/../packaging/Jarvis.app"
TARGET_DIR="$HOME/Applications"
TARGET_APP="$TARGET_DIR/Jarvis.app"

mkdir -p "$TARGET_DIR"
ditto "$SOURCE_APP" "$TARGET_APP"
swiftc "$SCRIPT_DIR/../packaging/JarvisLauncher.swift" \
    "$SCRIPT_DIR/../packaging/JarvisAccessibility.swift" \
    "$SCRIPT_DIR/../packaging/JarvisWindowManager.swift" \
    "$SCRIPT_DIR/../packaging/JarvisCalendar.swift" \
    "$SCRIPT_DIR/../packaging/JarvisVision.swift" \
    "$SCRIPT_DIR/../packaging/JarvisNotion.swift" \
    "$SCRIPT_DIR/../packaging/JarvisEmotionOverlay.swift" \
    -o "$TARGET_APP/Contents/MacOS/Jarvis"
# A plain ad-hoc signature uses the changing executable hash as its designated
# requirement. That makes macOS treat every development rebuild as a different
# app and invalidates Accessibility consent. Keep a stable local requirement.
codesign --force --deep --sign - \
    --identifier "com.federico.jarvis" \
    --requirements '=designated => identifier "com.federico.jarvis"' \
    "$TARGET_APP"
touch "$TARGET_APP"
echo "Installed $TARGET_APP"
