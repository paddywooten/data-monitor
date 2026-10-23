#!/usr/bin/env bash
# Data Monitor - build, install and uninstall for macOS.
#
#   ./build-mac.sh              build "dist/Data Monitor.app" + a .dmg
#   ./build-mac.sh build        same
#   ./build-mac.sh install      copy to ~/Applications and start hidden at
#                               login (LaunchAgent)
#   ./build-mac.sh uninstall    remove both again (keeps your data)
#
# Requirements: Homebrew (https://brew.sh), then run once:
#   brew install gtk4 libadwaita glib gdk-pixbuf cairo pango \
#                pygobject pycairo python psutil pyinstaller dbus
#
# The .dmg is ad-hoc signed only; Gatekeeper will warn about an unidentified
# developer (right-click > Open, or see README "Building for macOS").
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACTION="${1:-build}"
APP="$ROOT/dist/Data Monitor.app"
APPDIR="$HOME/Applications/Data Monitor.app"
AGENT="$HOME/Library/LaunchAgents/io.datamonitor.App.plist"
LABEL="io.datamonitor.App"
DATA_DIR="$HOME/Library/Application Support/datamonitor"
CONFIG_DIR="$HOME/Library/Preferences/datamonitor"
PYTHON=""

die() { echo "error: $*" >&2; exit 1; }

find_python() {
    local candidate
    for candidate in \
        "$(brew --prefix python 2>/dev/null)/bin/python3" \
        "$(command -v python3 || true)"; do
        [ -n "$candidate" ] && [ -x "$candidate" ] || continue
        if "$candidate" -c 'import gi, cairo' >/dev/null 2>&1; then
            PYTHON="$candidate"
            return 0
        fi
    done
    cat >&2 <<'MSG'
error: no Python with PyGObject + pycairo found.

Install the toolchain with Homebrew, then re-run this script:
  brew install gtk4 libadwaita glib gdk-pixbuf cairo pango \
               pygobject pycairo python psutil pyinstaller dbus
MSG
    exit 1
}

check_deps() {
    "$PYTHON" -c 'import psutil' >/dev/null 2>&1 ||
        "$PYTHON" -m pip install psutil ||
        die "pip could not install psutil (try: brew install psutil)"
    "$PYTHON" -c 'import PyInstaller' >/dev/null 2>&1 ||
        "$PYTHON" -m pip install pyinstaller ||
        die "pip could not install pyinstaller (try: brew install pyinstaller)"
}

build() {
    find_python
    check_deps

    echo "Building with $PYTHON ..."
    (cd "$ROOT" && "$PYTHON" -m PyInstaller --noconfirm --clean packaging/datamonitor.spec)

    # GLib needs a compiled schema cache inside the bundle.
    local schemas="$ROOT/dist/Data Monitor.app/Contents/Frameworks/share/glib-2.0/schemas"
    if command -v glib-compile-schemas >/dev/null 2>&1 && [ -d "$schemas" ]; then
        glib-compile-schemas "$schemas" || true
    fi

    # Apple Silicon refuses completely unsigned code; ad-hoc is enough for
    # running locally (real distribution needs a Developer ID + notarisation).
    codesign --force --deep --sign - "$APP" 2>/dev/null ||
        echo "warning: ad-hoc codesign failed; the app may not launch on Apple Silicon" >&2

    make_dmg

    echo
    echo "Done."
    echo "  App : $APP"
    echo "  DMG : $ROOT/dist/DataMonitor-$(version).dmg"
    echo "  Install it:  ./build-mac.sh install"
}

version() {
    sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/datamonitor/__init__.py"
}

make_dmg() {
    local dmg stage
    dmg="$ROOT/dist/DataMonitor-$(version).dmg"
    stage="$(mktemp -d)"
    cp -R "$APP" "$stage/"
    ln -s /Applications "$stage/Applications"
    rm -f "$dmg"
    hdiutil create -volname "Data Monitor" -srcfolder "$stage" -ov -format UDZO "$dmg" >/dev/null
    rm -rf "$stage"
    codesign --force --sign - "$dmg" 2>/dev/null || true
    echo "  dmg        -> $dmg"
}

install_app() {
    [ -d "$APP" ] || die "no build found at \"$APP\" - run ./build-mac.sh first"

    echo "Installing to \"$APPDIR\" ..."
    osascript -e 'quit app "Data Monitor"' >/dev/null 2>&1 || true
    sleep 1
    mkdir -p "$HOME/Applications"
    rm -rf "$APPDIR"
    cp -R "$APP" "$APPDIR"

    mkdir -p "$(dirname "$AGENT")"
    cat > "$AGENT" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$APPDIR/Contents/MacOS/DataMonitor</string>
        <string>--hidden</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>ProcessType</key>
    <string>Interactive</string>
</dict>
</plist>
EOF
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$AGENT" 2>/dev/null ||
        launchctl load "$AGENT" 2>/dev/null || true

    echo "  app       -> $APPDIR"
    echo "  autostart -> $AGENT (starts hidden at login)"
    echo
    echo "Start it now with:  open \"$APPDIR\""
    echo "Open a tab with:    \"$APPDIR/Contents/MacOS/DataMonitor\" --page history"
}

uninstall_app() {
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null ||
        launchctl unload "$AGENT" 2>/dev/null || true
    osascript -e 'quit app "Data Monitor"' >/dev/null 2>&1 || true
    rm -f "$AGENT"
    rm -rf "$APPDIR"
    echo "Removed the login item and \"$APPDIR\"."
    echo
    echo "Your data stays in \"$DATA_DIR\" and \"$CONFIG_DIR\"."
    echo "Delete those folders by hand for a full reset."
}

case "$ACTION" in
    build) build ;;
    install) install_app ;;
    uninstall) uninstall_app ;;
    *)
        echo "build-mac.sh: unknown action '$ACTION' (use build, install or uninstall)" >&2
        exit 2
        ;;
esac
