#!/usr/bin/env bash
# Claude Monitor hook - forwards all Claude Code events to the monitor daemon
# This script is registered as a hook for multiple Claude Code events.
# It reads the hook event JSON from stdin and POSTs it to the daemon.

MONITOR_URL="${CLAUDE_MONITOR_URL:-http://localhost:7483/hook}"
TTY_NAME=$(tty 2>/dev/null || echo "unknown")

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
