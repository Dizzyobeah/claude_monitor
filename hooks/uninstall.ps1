# Remove Claude Monitor plugin and marketplace from Claude Code

#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Write-Host "Claude Monitor Plugin Uninstaller"
Write-Host "==================================="

$claudeCmd = Get-Command claude -ErrorAction SilentlyContinue
if (-not $claudeCmd) {
    Write-Host "ERROR: 'claude' CLI not found in PATH."
    exit 1
}

& claude plugin uninstall claude-monitor
try { & claude plugin marketplace remove claude-monitor } catch {}

Write-Host ""
Write-Host "Uninstall complete."
