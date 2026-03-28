#!/usr/bin/env bash
# Remove Claude Monitor hooks from Claude Code settings and shell rc env vars

set -euo pipefail

SETTINGS_FILE="${HOME}/.claude/settings.json"

echo "Claude Monitor Hook Uninstaller"
echo "================================"

if [ ! -f "$SETTINGS_FILE" ]; then
    echo "No settings file found at $SETTINGS_FILE - nothing to do."
    exit 0
fi

uv run python3 -c "
import json

settings_file = '$SETTINGS_FILE'

with open(settings_file) as f:
    settings = json.load(f)

hooks = settings.get('hooks', {})
removed = 0

for event in list(hooks.keys()):
    filtered = []
    for entry in hooks[event]:
        has_monitor = any(
            sub.get('command', '').endswith('claude-monitor-hook.sh')
            for sub in entry.get('hooks', [])
        )
        if has_monitor:
            removed += 1
        else:
            filtered.append(entry)

    if filtered:
        hooks[event] = filtered
    else:
        del hooks[event]

settings['hooks'] = hooks

with open(settings_file, 'w') as f:
    json.dump(settings, f, indent=2)

print(f'Removed {removed} Claude Monitor hook entries.')
"

# --------------------------------------------------------------------------
# Remove CLAUDE_MONITOR_DIR from shell rc files
# --------------------------------------------------------------------------
echo ""
echo "Removing CLAUDE_MONITOR_DIR from shell rc files:"
REMOVED_ANY=false

remove_from_rc() {
    local rc_file="$1"
    if [ -f "$rc_file" ] && grep -q 'CLAUDE_MONITOR_DIR' "$rc_file"; then
        grep -v 'CLAUDE_MONITOR_DIR' "$rc_file" > "${rc_file}.tmp" && mv "${rc_file}.tmp" "$rc_file" || true
        echo "  Cleaned: $rc_file"
        REMOVED_ANY=true
    fi
}

remove_from_rc "${HOME}/.bashrc"
remove_from_rc "${HOME}/.zshrc"
remove_from_rc "${HOME}/.bash_profile"

# Fish shell
FISH_CONF="${HOME}/.config/fish/conf.d/claude-monitor.fish"
if [ -f "$FISH_CONF" ]; then
    rm -f "$FISH_CONF"
    echo "  Removed: $FISH_CONF"
    REMOVED_ANY=true
fi

if [ "$REMOVED_ANY" = false ]; then
    echo "  No CLAUDE_MONITOR_DIR entries found in shell rc files."
fi
# --------------------------------------------------------------------------

echo ""
echo "Uninstall complete."
