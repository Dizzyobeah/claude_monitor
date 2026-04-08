#!/usr/bin/env bash
# Install Claude Monitor as a Claude Code plugin
# Registers the repo as a local marketplace, installs the plugin, and injects hooks.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HOOK_SCRIPT="$SCRIPT_DIR/claude-monitor-hook.sh"
SETTINGS_FILE="$HOME/.claude/settings.json"

echo "Claude Monitor Plugin Installer"
echo "================================"
echo ""

# Make hook executable
chmod +x "$HOOK_SCRIPT"

if ! command -v claude >/dev/null 2>&1; then
    echo "ERROR: 'claude' CLI not found in PATH."
    echo "Install Claude Code first: https://claude.ai/code"
    exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "ERROR: 'jq' not found in PATH. Install it first (e.g. brew install jq)."
    exit 1
fi

# Register the repo as a local marketplace and install the plugin
claude plugin marketplace add "$REPO_ROOT"
claude plugin install claude-monitor

# Inject hooks into ~/.claude/settings.json
echo "Registering hooks in $SETTINGS_FILE..."

# Ensure settings file exists with at least an empty object
if [ ! -f "$SETTINGS_FILE" ]; then
    echo "{}" > "$SETTINGS_FILE"
fi

# The hook entry to add for each event
HOOK_ENTRY="{\"matcher\": \"*\", \"hooks\": [{\"type\": \"command\", \"command\": \"$HOOK_SCRIPT\", \"timeout\": 5, \"async\": true}]}"

# Events that need the monitor hook
EVENTS=(
    "SessionStart"
    "SessionEnd"
    "SubagentStart"
    "UserPromptSubmit"
    "Stop"
    "Notification"
    "PermissionRequest"
    "PostToolUseFailure"
    "PreToolUse"
    "PostToolUse"
    "StopFailure"
    "SubagentStop"
)

for event in "${EVENTS[@]}"; do
    # Check if a hook with this command is already registered for this event
    already=$(jq --arg event "$event" --arg cmd "$HOOK_SCRIPT" \
        '(.hooks[$event] // []) | map(select(.hooks[]?.command == $cmd)) | length' \
        "$SETTINGS_FILE" 2>/dev/null || echo 0)

    if [ "$already" -gt 0 ]; then
        echo "  $event: already registered, skipping"
    else
        tmp=$(mktemp)
        jq --arg event "$event" --argjson hook "$HOOK_ENTRY" \
            '.hooks[$event] = (.hooks[$event] // []) + [$hook]' \
            "$SETTINGS_FILE" > "$tmp" && mv "$tmp" "$SETTINGS_FILE"
        echo "  $event: hook added"
    fi
done

echo ""
echo "Plugin installed successfully."
echo ""
echo "Next steps:"
echo "  1. Flash the ESP32:   cd firmware && pio run -e e32r28t -t upload"
echo "  2. Power on the display (any USB power source)"
echo "  3. Start Claude Code — the daemon will start automatically"
echo "     on your first session (or run manually: cd daemon && uv run claude-monitor)"
echo ""
echo "To uninstall: bash $SCRIPT_DIR/uninstall.sh"
