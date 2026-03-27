#!/usr/bin/env bash
# Remove Claude Monitor hooks from Claude Code settings

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

echo "Uninstall complete."
