#!/usr/bin/env bash
# Claude Monitor hook - forwards all Claude Code events to the monitor daemon
# This script is registered as a hook for multiple Claude Code events.
# It reads the hook event JSON from stdin and POSTs it to the daemon.
# Auto-starts the daemon if it is not already running.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

MONITOR_URL="${CLAUDE_MONITOR_URL:-http://localhost:7483/hook}"
HEALTH_URL="${MONITOR_URL%/hook}/health"
TTY_NAME=$(tty 2>/dev/null) || TTY_NAME="unknown"

# --------------------------------------------------------------------------
# Daemon auto-start
# Probe /health before forwarding the event. If the daemon is not responding,
# start it in the background then wait briefly for the HTTP port to bind.
# --------------------------------------------------------------------------
if ! curl -sf --max-time 1 "$HEALTH_URL" >/dev/null 2>&1; then
    DAEMON_DIR="$REPO_ROOT/daemon"
    if [ -d "$DAEMON_DIR" ]; then
        # Start daemon detached; log goes to /tmp so it's always writable
        (cd "$DAEMON_DIR" && nohup uv run claude-monitor \
            >>"${TMPDIR:-/tmp}/claude-monitor.log" 2>&1 &)

        # Poll /health until the daemon is ready (up to 2 seconds)
        for _ in {1..10}; do
            sleep 0.2
            curl -sf --max-time 0.5 "$HEALTH_URL" >/dev/null 2>&1 && break
        done
    fi
fi
# --------------------------------------------------------------------------

# Read stdin (hook event JSON)
INPUT=$(cat)

# POST to daemon with TTY and PPID metadata
# Runs in background to never block Claude Code
curl -s -X POST "$MONITOR_URL" \
  -H "Content-Type: application/json" \
  -H "X-TTY: $TTY_NAME" \
  -H "X-PPID: $PPID" \
  -d "$INPUT" \
  --connect-timeout 1 \
  --max-time 2 \
  >/dev/null 2>&1 &

# Exit 0 immediately - never block Claude Code
exit 0
