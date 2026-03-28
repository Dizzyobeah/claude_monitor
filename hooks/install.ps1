# Install Claude Monitor hooks into Claude Code settings
# This adds hook entries for all relevant events

#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot    = Split-Path -Parent $ScriptDir   # hooks/ is one level below repo root
$HookScript  = Join-Path $ScriptDir 'claude-monitor-hook.ps1'
$SettingsFile = Join-Path $env:USERPROFILE '.claude\settings.json'

Write-Host "Claude Monitor Hook Installer"
Write-Host "=============================="
Write-Host "Hook script: $HookScript"
Write-Host "Settings:    $SettingsFile"
Write-Host ""

# Ensure .claude directory exists
$ClaudeDir = Join-Path $env:USERPROFILE '.claude'
if (-not (Test-Path $ClaudeDir)) {
    New-Item -ItemType Directory -Path $ClaudeDir | Out-Null
}

# Create settings file if it doesn't exist
if (-not (Test-Path $SettingsFile)) {
    '{}' | Set-Content -Path $SettingsFile -Encoding UTF8
}

$Events = @(
    'SessionStart'
    'SessionEnd'
    'UserPromptSubmit'
    'PreToolUse'
    'PostToolUse'
    'PostToolUseFailure'
    'PermissionRequest'
    'Notification'
    'Stop'
    'StopFailure'
    'SubagentStart'
    'SubagentStop'
)

# Use uv-managed Python to update settings.json (same as the bash version)
$PythonScript = @"
import json

settings_file = r'$($SettingsFile -replace '\\', '\\')'
hook_script   = r'$($HookScript  -replace '\\', '\\')'
events        = $(($Events | ForEach-Object { "'$_'" }) -join ', ' | ForEach-Object { "[$_]" })

with open(settings_file, encoding='utf-8') as f:
    settings = json.load(f)

if 'hooks' not in settings:
    settings['hooks'] = {}

hook_entry = {
    'matcher': '*',
    'hooks': [{
        'type': 'command',
        'command': f'powershell -NonInteractive -NoProfile -File "{hook_script}"',
        'timeout': 5,
    }]
}

for event in events:
    existing = settings['hooks'].get(event, [])
    # Remove any existing claude-monitor hooks
    existing = [h for h in existing if not any(
        'claude-monitor-hook' in sub.get('command', '')
        for sub in h.get('hooks', [])
    )]
    existing.append(hook_entry)
    settings['hooks'][event] = existing

with open(settings_file, 'w', encoding='utf-8') as f:
    json.dump(settings, f, indent=2)

print(f'Registered hooks for {len(events)} events.')
"@

uv run python -c $PythonScript

# --------------------------------------------------------------------------
# Set CLAUDE_MONITOR_DIR so the hook script can auto-start the daemon.
# Stored as a User-scope environment variable — survives reboots without
# requiring admin rights. Re-running install updates it if the repo moves.
# --------------------------------------------------------------------------
$currentVal = [Environment]::GetEnvironmentVariable('CLAUDE_MONITOR_DIR', 'User')
if ($currentVal -ne $RepoRoot) {
    [Environment]::SetEnvironmentVariable('CLAUDE_MONITOR_DIR', $RepoRoot, 'User')
    Write-Host ""
    Write-Host "Set CLAUDE_MONITOR_DIR = $RepoRoot  (User environment variable)"
    Write-Host "  -> The hook will auto-start the daemon on your first session."
    Write-Host "  -> Re-run this script if you move the repo."
} else {
    Write-Host ""
    Write-Host "CLAUDE_MONITOR_DIR already set to: $RepoRoot"
}
# Also set it for the current process so the hook works immediately without a relaunch
$env:CLAUDE_MONITOR_DIR = $RepoRoot
# --------------------------------------------------------------------------

Write-Host ""
Write-Host "Installation complete!"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Flash the ESP32:   cd firmware; pio run -e e32r28t -t upload"
Write-Host "  2. Power on the display (any USB power source)"
Write-Host "  3. Start Claude Code — the daemon will start automatically"
Write-Host "     on your first session (or run manually: cd daemon; uv run claude-monitor)"
Write-Host ""
Write-Host "To uninstall: powershell -File `"$ScriptDir\uninstall.ps1`""
