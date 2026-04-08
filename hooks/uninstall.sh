#!/usr/bin/env bash
# Remove Claude Monitor plugin, marketplace, and hooks from Claude Code

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOOK_SCRIPT="$SCRIPT_DIR/claude-monitor-hook.sh"
SETTINGS_FILE="$HOME/.claude/settings.json"

echo "Claude Monitor Plugin Uninstaller"
echo "==================================="

if ! command -v claude >/dev/null 2>&1; then
    echo "ERROR: 'claude' CLI not found in PATH."
    exit 1
fi

claude plugin uninstall claude-monitor
claude plugin marketplace remove claude-monitor 2>/dev/null || true

# Remove monitor hooks from ~/.claude/settings.json
if [ -f "$SETTINGS_FILE" ] && command -v jq >/dev/null 2>&1; then
    echo ""
    echo "Removing hooks from $SETTINGS_FILE..."

    EVENTS=(
        "SessionStart" "SessionEnd" "SubagentStart" "UserPromptSubmit"
        "Stop" "Notification" "PermissionRequest" "PostToolUseFailure"
        "PreToolUse" "PostToolUse" "StopFailure" "SubagentStop"
    )

    for event in "${EVENTS[@]}"; do
        tmp=$(mktemp)
        jq --arg event "$event" --arg cmd "$HOOK_SCRIPT" \
            'if .hooks[$event] then .hooks[$event] |= map(select(.hooks[]?.command != $cmd)) else . end' \
            "$SETTINGS_FILE" > "$tmp" && mv "$tmp" "$SETTINGS_FILE"
        echo "  $event: hook removed"
    done
fi

echo ""
echo "Uninstall complete."
