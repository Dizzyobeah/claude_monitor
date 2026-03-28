#!/usr/bin/env bash
# Remove Claude Monitor plugin and marketplace from Claude Code

set -euo pipefail

echo "Claude Monitor Plugin Uninstaller"
echo "==================================="

if ! command -v claude >/dev/null 2>&1; then
    echo "ERROR: 'claude' CLI not found in PATH."
    exit 1
fi

claude plugin uninstall claude-monitor
claude plugin marketplace remove claude-monitor 2>/dev/null || true

echo ""
echo "Uninstall complete."
