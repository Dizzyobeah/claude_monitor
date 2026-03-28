#!/usr/bin/env bash
# Install Claude Monitor hooks into Claude Code settings
# This adds hook entries for all relevant events

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"   # hooks/ is one level below repo root
HOOK_SCRIPT="$SCRIPT_DIR/claude-monitor-hook.sh"
SETTINGS_FILE="${HOME}/.claude/settings.json"

# Make hook executable
chmod +x "$HOOK_SCRIPT"

echo "Claude Monitor Hook Installer"
echo "=============================="
echo "Hook script: $HOOK_SCRIPT"
echo "Settings:    $SETTINGS_FILE"
echo ""

# Ensure .claude directory exists
mkdir -p "${HOME}/.claude"

# Create settings file if it doesn't exist
if [ ! -f "$SETTINGS_FILE" ]; then
    echo '{}' > "$SETTINGS_FILE"
fi

# Events we want to monitor
EVENTS=(
    "SessionStart"
    "SessionEnd"
    "UserPromptSubmit"
    "PreToolUse"
    "PostToolUse"
    "PostToolUseFailure"
    "PermissionRequest"
    "Notification"
    "Stop"
    "StopFailure"
    "SubagentStart"
    "SubagentStop"
)

# Build the hooks JSON using uv-managed Python
uv run python3 -c "
import json
import sys

settings_file = '$SETTINGS_FILE'
hook_script = '$HOOK_SCRIPT'
events = '${EVENTS[*]}'.split()

# Read existing settings
with open(settings_file) as f:
    settings = json.load(f)

# Ensure hooks key exists
if 'hooks' not in settings:
    settings['hooks'] = {}

hook_entry = {
    'matcher': '*',
    'hooks': [{
        'type': 'command',
        'command': hook_script,
        'timeout': 5,
    }]
}

# Add/update hooks for each event
for event in events:
    existing = settings['hooks'].get(event, [])
    # Remove any existing claude-monitor hooks
    existing = [h for h in existing if not any(
        sub.get('command', '').endswith('claude-monitor-hook.sh')
        for sub in h.get('hooks', [])
    )]
    existing.append(hook_entry)
    settings['hooks'][event] = existing

# Write back
with open(settings_file, 'w') as f:
    json.dump(settings, f, indent=2)

print(f'Registered hooks for {len(events)} events.')
"

# --------------------------------------------------------------------------
# Set CLAUDE_MONITOR_DIR so the hook script can auto-start the daemon.
# Write export lines into the user's shell rc files — survives reboots.
# Re-running install updates them if the repo moves.
# --------------------------------------------------------------------------
EXPORT_LINE="export CLAUDE_MONITOR_DIR=\"$REPO_ROOT\""
WROTE_ANY=false

write_to_rc() {
    local rc_file="$1"
    if [ -f "$rc_file" ]; then
        # Remove any previous CLAUDE_MONITOR_DIR line, then append the new one
        grep -v 'CLAUDE_MONITOR_DIR' "$rc_file" > "${rc_file}.tmp" && mv "${rc_file}.tmp" "$rc_file" || true
        echo "$EXPORT_LINE" >> "$rc_file"
        echo "  Updated: $rc_file"
        WROTE_ANY=true
    fi
}

echo ""
echo "Setting CLAUDE_MONITOR_DIR=$REPO_ROOT in shell rc files:"
write_to_rc "${HOME}/.bashrc"
write_to_rc "${HOME}/.zshrc"
write_to_rc "${HOME}/.bash_profile"

# Fish shell
FISH_CONF="${HOME}/.config/fish/conf.d/claude-monitor.fish"
if [ -d "$(dirname "$FISH_CONF")" ]; then
    echo "set -gx CLAUDE_MONITOR_DIR \"$REPO_ROOT\"" > "$FISH_CONF"
    echo "  Updated: $FISH_CONF"
    WROTE_ANY=true
fi

if [ "$WROTE_ANY" = false ]; then
    echo "  No shell rc files found — add the following line manually:"
    echo "  $EXPORT_LINE"
fi

# Also export for the current shell session
export CLAUDE_MONITOR_DIR="$REPO_ROOT"
echo "  -> The hook will auto-start the daemon on your first session."
echo "  -> Re-run this script if you move the repo."
# --------------------------------------------------------------------------

echo ""
echo "Installation complete!"
echo ""
echo "Next steps:"
echo "  1. Flash the ESP32:   cd firmware && pio run -e e32r28t -t upload"
echo "  2. Power on the display (any USB power source)"
echo "  3. Start Claude Code — the daemon will start automatically"
echo "     on your first session (or run manually: cd daemon && uv run claude-monitor)"
echo ""
echo "To uninstall: bash $SCRIPT_DIR/uninstall.sh"
