#!/usr/bin/env bash
# Install (or reinstall) the Gideon web face as a macOS login agent.
# It starts http://127.0.0.1:8000 at login and restarts if it crashes.
#
#   bash scripts/install-login-agent.sh           # install + start now
#   bash scripts/install-login-agent.sh uninstall # stop + remove
set -euo pipefail

LABEL="com.gideon.web"
SRC="$(cd "$(dirname "$0")/.." && pwd)/launch/${LABEL}.plist"
DEST="$HOME/Library/LaunchAgents/${LABEL}.plist"
DOMAIN="gui/$(id -u)"

if [[ "${1:-}" == "uninstall" ]]; then
  launchctl bootout "$DOMAIN" "$DEST" 2>/dev/null || launchctl unload "$DEST" 2>/dev/null || true
  rm -f "$DEST"
  echo "Removed $LABEL."
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents"
cp "$SRC" "$DEST"

# Reload cleanly (bootout first in case it's already loaded).
launchctl bootout "$DOMAIN" "$DEST" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$DEST" 2>/dev/null || launchctl load -w "$DEST"

echo "Installed $LABEL. Gideon's face will start at login (and is starting now)."
echo "Open http://127.0.0.1:8000  ·  logs: state/web.log"
echo "Stop/remove with: bash scripts/install-login-agent.sh uninstall"
