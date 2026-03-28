# Remove Claude Monitor hooks from Claude Code settings (Windows)
# Mirrors uninstall.sh for Windows users.

#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$SettingsFile = Join-Path $env:USERPROFILE '.claude\settings.json'

Write-Host "Claude Monitor Hook Uninstaller"
Write-Host "================================"

if (-not (Test-Path $SettingsFile)) {
    Write-Host "No settings file found at $SettingsFile - nothing to do."
    exit 0
}

$PythonScript = @"
import json

settings_file = r'$($SettingsFile -replace '\\', '\\')'

with open(settings_file, encoding='utf-8') as f:
    settings = json.load(f)

hooks = settings.get('hooks', {})
removed = 0

for event in list(hooks.keys()):
    filtered = []
    for entry in hooks[event]:
        has_monitor = any(
            'claude-monitor-hook' in sub.get('command', '')
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

with open(settings_file, 'w', encoding='utf-8') as f:
    json.dump(settings, f, indent=2)

print(f'Removed {removed} Claude Monitor hook entries.')
"@

uv run python -c $PythonScript

# Clear CLAUDE_MONITOR_DIR persistent env var if it was set by our installer
$existing = [Environment]::GetEnvironmentVariable('CLAUDE_MONITOR_DIR', 'User')
if ($existing) {
    [Environment]::SetEnvironmentVariable('CLAUDE_MONITOR_DIR', $null, 'User')
    Remove-Item Env:CLAUDE_MONITOR_DIR -ErrorAction SilentlyContinue
    Write-Host "Cleared CLAUDE_MONITOR_DIR environment variable."
}

Write-Host ""
Write-Host "Uninstall complete."
