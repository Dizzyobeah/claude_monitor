#!/usr/bin/env bash
# Install Claude Monitor as a Claude Code plugin
# Registers the repo as a local marketplace, then installs the plugin.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HOOK_SCRIPT="$SCRIPT_DIR/claude-monitor-hook.sh"

echo "Claude Monitor Plugin Installer"
echo "================================"
echo ""

# Make hook executable
chmod +x "$HOOK_SCRIPT"

if ! command -v claude >/dev/null 2>&1; then
    echo "ERROR: 'claude' CLI not found in PATH."
    echo "Install Claude Code first: https://claude.ai/code"
    exit 1
fi

# Register the repo as a local marketplace and install the plugin
claude plugin marketplace add "$REPO_ROOT"
claude plugin install claude-monitor

echo ""
echo "Plugin installed successfully."
echo ""
echo "Next steps:"
echo "  1. Flash the ESP32:   cd firmware && pio run -e e32r28t -t upload"
echo "  2. Power on the display (any USB power source)"
echo "  3. Start Claude Code — the daemon will start automatically"
echo "     on your first session (or run manually: cd daemon && uv run claude-monitor)"
echo ""
echo "To uninstall: bash $SCRIPT_DIR/uninstall.sh"
