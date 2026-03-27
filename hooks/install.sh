#!/usr/bin/env bash
# Install Claude Monitor hooks into Claude Code settings
# This adds hook entries for all relevant events

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
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

echo ""
echo "Installation complete!"
echo ""
echo "Next steps:"
echo "  1. Flash the ESP32:   cd firmware && pio run -e e32r28t -t upload"
echo "  2. Power on the display (any USB power source)"
echo "  3. Start the daemon:  cd daemon && uv run claude-monitor"
echo "     (auto-discovers display via Bluetooth)"
echo "  4. Start Claude Code - the display will show session status"
echo ""
echo "To uninstall: bash $SCRIPT_DIR/uninstall.sh"
