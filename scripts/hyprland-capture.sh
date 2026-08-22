#!/bin/bash
# Hyprland keybinding helper — opens Palimind capture popup
#
# Add this to your ~/.config/hypr/hyprland.conf:
#   bind = CTRL ALT SHIFT, SPACE, exec, /path/to/palimind/scripts/hyprland-capture.sh
#
# On Wayland, Tauri global shortcuts don't work, so this script
# calls the backend's /api/hotkey/trigger endpoint.  The Python backend
# broadcasts an SSE event to the main Tauri window, whose JavaScript
# opens the capture WebView popup.

set -euo pipefail

PALIMIND_URL="http://127.0.0.1:8000"

# 1. Check if Palimind backend is running (use /api/fields, always returns 200)
if ! curl -sf "$PALIMIND_URL/api/fields" > /dev/null 2>&1; then
    notify-send -a Palimind "Palimind is not running" "Start Palimind first, then try the keybinding again."
    exit 1
fi

# 2. Trigger the capture popup — the backend broadcasts an SSE event,
#    the main window JS receives it and opens the Tauri WebView popup.
curl -sf -X POST "$PALIMIND_URL/api/hotkey/trigger" > /dev/null 2>&1 || {
    # Fallback: open capture page in browser
    xdg-open "$PALIMIND_URL/ui/hotkey"
}
