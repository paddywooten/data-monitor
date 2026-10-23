#!/usr/bin/env bash
# Remove Datawatch. Usage:
#   ./uninstall.sh               remove app, launcher, icon, menu + autostart
#   ./uninstall.sh --purge       also delete the history database and settings
set -euo pipefail

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
APP_ID="io.datawatch.App"
APP_HOME="$DATA_HOME/datawatch"

PURGE=0
for arg in "$@"; do
    case "$arg" in
        --keep-data) PURGE=0 ;;
        --purge) PURGE=1 ;;
        -h|--help) sed -n '2,4p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "uninstall.sh: unknown option '$arg'" >&2; exit 2 ;;
    esac
done

remove() {
    if [[ -e "$1" ]]; then
        rm -rf -- "$1"
        echo "  removed $1"
    fi
}

if command -v systemctl >/dev/null; then
    systemctl --user disable --now datawatch.service >/dev/null 2>&1 || true
    systemctl --user daemon-reload >/dev/null 2>&1 || true
fi

remove "$HOME/.local/bin/datawatch"
remove "$DATA_HOME/applications/$APP_ID.desktop"
remove "$CONFIG_HOME/autostart/datawatch.desktop"
remove "$DATA_HOME/icons/hicolor/scalable/apps/datawatch.svg"
remove "$CONFIG_HOME/systemd/user/datawatch.service"

if [[ "$PURGE" -eq 1 ]]; then
    remove "$APP_HOME"                 # installed package + history.sqlite3
    remove "$CONFIG_HOME/datawatch"    # settings
    echo "  history and settings deleted"
else
    # Keep history.sqlite3 next to the installed package.
    remove "$APP_HOME/datawatch"
    echo "  history kept in $APP_HOME/history.sqlite3 (use --purge to delete it)"
fi

echo "Datawatch uninstalled."
