# Install Claude Monitor plugin for OpenCode
# Copies the plugin to ~/.config/opencode/plugins/ (OpenCode's global plugin dir on Windows)

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = Split-Path -Parent $ScriptDir   # hooks/ is one level below repo root
$PluginSrc  = Join-Path $ScriptDir "opencode-plugin.js"
$PluginDir  = Join-Path $HOME ".config\opencode\plugins"
$PluginDst  = Join-Path $PluginDir "claude-monitor.js"

Write-Host "Claude Monitor OpenCode Plugin Installer"
Write-Host "========================================="
Write-Host "Plugin: $PluginDst"
Write-Host ""

if (-not (Test-Path $PluginSrc)) {
    Write-Error "Plugin source not found: $PluginSrc"
    exit 1
}

New-Item -ItemType Directory -Force -Path $PluginDir | Out-Null
Copy-Item -Force $PluginSrc $PluginDst

Write-Host "Installed!"

# --------------------------------------------------------------------------
# Set CLAUDE_MONITOR_DIR so the plugin can auto-start the daemon.
# Stored as a User-scoped persistent environment variable.
# --------------------------------------------------------------------------
Write-Host ""
Write-Host "Setting CLAUDE_MONITOR_DIR=$RepoRoot ..."
[Environment]::SetEnvironmentVariable('CLAUDE_MONITOR_DIR', $RepoRoot, 'User')
$env:CLAUDE_MONITOR_DIR = $RepoRoot   # also active for the current session
Write-Host "  -> The plugin will auto-start the daemon when OpenCode loads."
Write-Host "  -> Re-run this script if you move the repo."
# --------------------------------------------------------------------------

Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Flash the ESP32:   cd firmware; pio run -e e32r28t -t upload"
Write-Host "  2. Power on the display (any USB power source)"
Write-Host "  3. Start OpenCode -- the daemon will start automatically"
Write-Host "     (or run manually: cd daemon; uv run claude-monitor)"
Write-Host ""
Write-Host "To uninstall: Remove-Item `"$PluginDst`""
