---
name: daemon-restart
description: Kill the running daemon, reinstall the package, and verify it starts cleanly. Use when the user wants to restart the daemon after code changes. (user)
allowed-tools: Bash
---

# Daemon Restart

Kill the running daemon process, reinstall the editable package so code changes take effect, and verify the health endpoint responds.

## Instructions

### 1. Kill existing daemon

```bash
pkill -f 'claude-monitor' 2>/dev/null || true
sleep 1
# Force-kill if still running
pkill -9 -f 'claude-monitor' 2>/dev/null || true
```

### 2. Reinstall the package

```bash
cd daemon
uv pip install -e .
```

### 3. Start the daemon

```bash
cd daemon
nohup uv run claude-monitor >> ~/.local/state/claude-monitor/daemon.log 2>&1 &
```

### 4. Verify health

Poll the health endpoint until it responds (up to 5 seconds):

```bash
for i in $(seq 1 10); do
    sleep 0.5
    if curl -sf --max-time 1 http://localhost:7483/health >/dev/null 2>&1; then
        echo "Daemon is healthy"
        curl -s http://localhost:7483/status
        break
    fi
    if [ "$i" = "10" ]; then
        echo "Daemon failed to start -- check ~/.local/state/claude-monitor/daemon.log"
    fi
done
```

Report the status output to the user.

## Usage Examples

```
/daemon-restart
```
