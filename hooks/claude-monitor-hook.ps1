# Claude Monitor hook - forwards all Claude Code events to the monitor daemon
# Registered as a hook for multiple Claude Code events.
# Reads the hook event JSON from stdin and POSTs it to the daemon.
# Auto-starts the daemon if it is not already running.

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Split-Path -Parent $ScriptDir

$MonitorUrl = if ($env:CLAUDE_MONITOR_URL) { $env:CLAUDE_MONITOR_URL } else { 'http://localhost:7483/hook' }
$HealthUrl  = $MonitorUrl -replace '/hook$', '/health'

# --------------------------------------------------------------------------
# Daemon auto-start
# Probe /health before forwarding the event. If the daemon is not responding,
# start it silently in the background then wait briefly for the HTTP port to bind.
# --------------------------------------------------------------------------
$daemonAlive = $false
try {
    Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 1 -ErrorAction Stop | Out-Null
    $daemonAlive = $true
} catch {}

if (-not $daemonAlive) {
    $daemonDir = Join-Path $RepoRoot 'daemon'
    if (Test-Path $daemonDir) {
        # Launch daemon fully detached from any console.
        # Redirecting stdout/stderr to a log file causes Windows to spawn the
        # process with no console attached at all — there is no window to
        # accidentally close, and no CTRL_CLOSE_EVENT can reach the daemon.
        $logFile = Join-Path $env:TEMP 'claude-monitor.log'
        Start-Process -FilePath 'cmd.exe' `
            -ArgumentList '/c', 'uv run claude-monitor' `
            -WorkingDirectory $daemonDir `
            -WindowStyle Hidden `
            -RedirectStandardOutput $logFile `
            -RedirectStandardError  $logFile `
            -ErrorAction SilentlyContinue
        # Wait for the HTTP server to bind (usually < 1s, 2s is generous)
        $waited = 0
        while ($waited -lt 2000) {
            Start-Sleep -Milliseconds 200
            $waited += 200
            try {
                Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 1 -ErrorAction Stop | Out-Null
                break
            } catch {}
        }
    }
}
# --------------------------------------------------------------------------

# Clean up any previously completed background jobs to prevent accumulation
Get-Job -State Completed -ErrorAction SilentlyContinue | Remove-Job -Force -ErrorAction SilentlyContinue
Get-Job -State Failed    -ErrorAction SilentlyContinue | Remove-Job -Force -ErrorAction SilentlyContinue

# Read stdin (hook event JSON)
$HookInput = [Console]::In.ReadToEnd()

# Capture metadata for terminal-finder: parent PID and a Windows sentinel for TTY
$ParentPid = try { (Get-Process -Id $PID -ErrorAction Stop).Parent.Id } catch { '' }
$TtyValue  = 'windows'   # No TTY concept on Windows; daemon uses PPID instead

# POST to daemon in background so we never block Claude Code.
# Prefer Start-ThreadJob (runs in-process thread, no subprocess overhead).
# Fall back to Start-Job if ThreadJob module is unavailable (PowerShell 5.1 without module).
$JobScript = {
    param($Url, $Body, $Ppid, $Tty)
    try {
        $Headers = @{
            'Content-Type' = 'application/json'
            'X-PPID'       = $Ppid
            'X-TTY'        = $Tty
        }
        Invoke-RestMethod -Uri $Url `
            -Method Post `
            -Headers $Headers `
            -Body $Body `
            -TimeoutSec 2 | Out-Null
    } catch {
        # Silently ignore - daemon may not be running
    }
}

$JobArgs = @($MonitorUrl, $HookInput, "$ParentPid", $TtyValue)

if (Get-Command Start-ThreadJob -ErrorAction SilentlyContinue) {
    Start-ThreadJob -ScriptBlock $JobScript -ArgumentList $JobArgs | Out-Null
} else {
    Start-Job    -ScriptBlock $JobScript -ArgumentList $JobArgs | Out-Null
}

# Exit immediately - never block Claude Code
exit 0
