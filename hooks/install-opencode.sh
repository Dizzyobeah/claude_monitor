#!/usr/bin/env bash
# Install Claude Monitor plugin for OpenCode
# Copies the plugin to ~/.config/opencode/plugins/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"   # hooks/ is one level below repo root
PLUGIN_SRC="$SCRIPT_DIR/opencode-plugin.js"
PLUGIN_DIR="${HOME}/.config/opencode/plugins"
PLUGIN_DST="$PLUGIN_DIR/claude-monitor.js"

echo "Claude Monitor OpenCode Plugin Installer"
echo "========================================="
echo "Plugin: $PLUGIN_DST"
echo ""

mkdir -p "$PLUGIN_DIR"
cp "$PLUGIN_SRC" "$PLUGIN_DST"

echo "Installed!"

# --------------------------------------------------------------------------
# Set CLAUDE_MONITOR_DIR so the plugin can auto-start the daemon.
# Write export lines into the user's shell rc files — survives reboots.
# Re-running install updates them if the repo moves.
# --------------------------------------------------------------------------
EXPORT_LINE="export CLAUDE_MONITOR_DIR=\"$REPO_ROOT\""
WROTE_ANY=false

write_to_rc() {
    local rc_file="$1"
    if [ -f "$rc_file" ]; then
        grep -v 'CLAUDE_MONITOR_DIR' "$rc_file" > "${rc_file}.tmp" && mv "${rc_file}.tmp" "$rc_file" || true
        echo "$EXPORT_LINE" >> "$rc_file"
        echo "  Updated: $rc_file"
        WROTE_ANY=true
    fi
}

echo ""
echo "Setting CLAUDE_MONITOR_DIR=$REPO_ROOT in shell rc files:"
write_to_rc "${HOME}/.bashrc"
write_to_rc "${HOME}/.zshrc"
write_to_rc "${HOME}/.bash_profile"

# Fish shell
FISH_CONF="${HOME}/.config/fish/conf.d/claude-monitor.fish"
if [ -d "$(dirname "$FISH_CONF")" ]; then
    echo "set -gx CLAUDE_MONITOR_DIR \"$REPO_ROOT\"" > "$FISH_CONF"
    echo "  Updated: $FISH_CONF"
    WROTE_ANY=true
fi

if [ "$WROTE_ANY" = false ]; then
    echo "  No shell rc files found — add the following line manually:"
    echo "  $EXPORT_LINE"
fi

# Also export for the current shell session
export CLAUDE_MONITOR_DIR="$REPO_ROOT"
echo "  -> The plugin will auto-start the daemon when OpenCode loads."
echo "  -> Re-run this script if you move the repo."
# --------------------------------------------------------------------------

echo ""
echo "Next steps:"
echo "  1. Flash the ESP32:   cd firmware && pio run -e e32r28t -t upload"
echo "  2. Power on the display (any USB power source)"
echo "  3. Start OpenCode — the daemon will start automatically"
echo "     (or run manually: cd daemon && uv run claude-monitor)"
echo ""
echo "To uninstall: rm \"$PLUGIN_DST\""
