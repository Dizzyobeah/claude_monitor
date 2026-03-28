# Install Claude Monitor as a Claude Code plugin
# Registers the repo as a local marketplace, then installs the plugin.

#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Split-Path -Parent $ScriptDir

Write-Host "Claude Monitor Plugin Installer"
Write-Host "================================"
Write-Host ""

$claudeCmd = Get-Command claude -ErrorAction SilentlyContinue
if (-not $claudeCmd) {
    Write-Host "ERROR: 'claude' CLI not found in PATH."
    Write-Host "Install Claude Code first: https://claude.ai/code"
    exit 1
}

# Register the repo as a local marketplace and install the plugin
& claude plugin marketplace add "$RepoRoot"
& claude plugin install claude-monitor

Write-Host ""
Write-Host "Plugin installed successfully."
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Flash the ESP32:   cd firmware; pio run -e e32r28t -t upload"
Write-Host "  2. Power on the display (any USB power source)"
Write-Host "  3. Start Claude Code — the daemon will start automatically"
Write-Host "     on your first session (or run manually: cd daemon; uv run claude-monitor)"
Write-Host ""
Write-Host "To uninstall: powershell -File `"$ScriptDir\uninstall.ps1`""
