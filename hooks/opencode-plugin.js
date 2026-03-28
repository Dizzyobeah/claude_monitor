/**
 * Claude Monitor plugin for OpenCode
 *
 * Forwards OpenCode session events to the Claude Monitor daemon so the
 * ESP32 display shows live session state, just like with Claude Code.
 *
 * Install (global): place in ~/.config/opencode/plugins/
 * Install (project): place in .opencode/plugins/
 *
 * Auto-start: if CLAUDE_MONITOR_DIR is set the plugin will start the daemon
 * automatically when OpenCode loads — no need to run it manually.
 */

const MONITOR_URL = process.env.CLAUDE_MONITOR_URL ?? "http://localhost:7483/hook";
const HEALTH_URL  = MONITOR_URL.replace(/\/hook$/, "/health");

/** POST to daemon, fire-and-forget, never throw. */
async function notify(body) {
  try {
    const headers = {
      "Content-Type": "application/json",
      // X-PPID lets the daemon walk the process tree to find the terminal window.
      // process.ppid is available in Node.js on all platforms (Linux, macOS, Windows).
      "X-PPID": String(process.pid ?? ""),
      // X-TTY is only meaningful on Unix; send "windows" on Windows so the daemon
      // can distinguish "no TTY info" from "running on Windows".
      "X-TTY": process.platform === "win32" ? "windows" : "",
    };
    await fetch(MONITOR_URL, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(2000),
    });
  } catch {
    // Daemon not running — silently ignore
  }
}

/**
 * Probe /health and, if the daemon is not running, start it from
 * CLAUDE_MONITOR_DIR/daemon using `uv run claude-monitor`.
 * Waits up to 2 s for the port to bind before returning.
 *
 * Returns true if a new daemon was started, false if it was already running
 * (or if it could not be started).
 */
async function ensureDaemonRunning() {
  // Fast path: daemon already up
  try {
    await fetch(HEALTH_URL, { signal: AbortSignal.timeout(1000) });
    return false; // already running
  } catch {}

  const monitorDir = process.env.CLAUDE_MONITOR_DIR;
  if (!monitorDir) return false; // can't start without knowing where the repo is

  const { join } = await import("node:path");
  const { existsSync, openSync } = await import("node:fs");
  const { spawn } = await import("node:child_process");

  const daemonDir = join(monitorDir, "daemon");
  if (!existsSync(daemonDir)) return false;

  // Open daemon-err.log for append so each run's output is preserved
  const logPath = join(monitorDir, "daemon-err.log");
  let logFd;
  try {
    logFd = openSync(logPath, "a");
  } catch {
    logFd = null;
  }
  const logOut = logFd != null ? logFd : "ignore";

  // Spawn detached so the daemon outlives the OpenCode process
  const isWindows = process.platform === "win32";
  const child = spawn(
    isWindows ? "cmd.exe" : "uv",
    isWindows ? ["/c", "uv run claude-monitor -v"] : ["run", "claude-monitor", "-v"],
    {
      cwd: daemonDir,
      detached: true,
      stdio: ["ignore", logOut, logOut],
      windowsHide: true,
    }
  );
  child.unref();

  // Poll /health until daemon is ready (up to 2 s in 200 ms steps)
  for (let i = 0; i < 10; i++) {
    await new Promise((r) => setTimeout(r, 200));
    try {
      await fetch(HEALTH_URL, { signal: AbortSignal.timeout(500) });
      return true; // freshly started
    } catch {}
  }
  return false; // started but didn't come up in time
}

export const ClaudeMonitorPlugin = async ({ directory, client }) => {
  // --------------------------------------------------------------------------
  // Daemon auto-start
  // The plugin factory runs once when OpenCode loads. This is the earliest
  // possible moment to ensure the daemon is up before any session events fire.
  // If OpenCode was already running with sessions open (e.g. daemon was killed
  // and restarted), we seed the daemon with those sessions immediately.
  // --------------------------------------------------------------------------
  const daemonWasFresh = await ensureDaemonRunning();

  // Track session directories so we can supply cwd on non-session events
  const sessionDirs = new Map();

  if (daemonWasFresh) {
    // Daemon was just started — seed it with any sessions already open.
    // This covers the case where OpenCode was running before the daemon.
    try {
      const res = await client.session.list();
      const sessions = res?.data ?? [];
      for (const session of sessions) {
        const cwd = session.directory ?? directory ?? "";
        sessionDirs.set(session.id, cwd);
        await notify({
          source: "opencode",
          hook_event_name: "SessionStart",
          session_id: session.id,
          cwd,
        });
      }
    } catch {
      // session.list() may fail if no sessions exist yet — silently ignore
    }
  }
  // --------------------------------------------------------------------------

  /**
   * Replay a SessionStart for every session the plugin currently knows about.
   * Called after starting a fresh daemon so it gets bootstrapped with the
   * sessions that were already open when it launched.
   */
  async function replayKnownSessions() {
    for (const [id, cwd] of sessionDirs) {
      await notify({
        source: "opencode",
        hook_event_name: "SessionStart",
        session_id: id,
        cwd,
      });
    }
  }

  return {
    event: async ({ event }) => {
      const type = event.type;
      const props = event.properties;

      switch (type) {
        case "session.created": {
          const session = props.info;
          sessionDirs.set(session.id, session.directory ?? directory ?? "");
          // Re-check daemon health: it may have auto-exited after the previous
          // session ended. If a fresh daemon was started, replay all known
          // sessions so the display is bootstrapped immediately.
          const started = await ensureDaemonRunning();
          if (started) {
            await replayKnownSessions();
          } else {
            await notify({
              source: "opencode",
              hook_event_name: "SessionStart",
              session_id: session.id,
              cwd: session.directory ?? directory ?? "",
            });
          }
          break;
        }

        case "session.deleted": {
          const session = props.info;
          sessionDirs.delete(session.id);
          await notify({
            source: "opencode",
            hook_event_name: "SessionEnd",
            session_id: session.id,
            cwd: session.directory ?? directory ?? "",
          });
          break;
        }

        case "session.idle": {
          const sessionID = props.sessionID;
          await notify({
            source: "opencode",
            hook_event_name: "Stop",
            session_id: sessionID,
            cwd: sessionDirs.get(sessionID) ?? directory ?? "",
          });
          break;
        }

        case "session.status": {
          const sessionID = props.sessionID;
          // props.status is a SessionStatus object: { type: "idle" | "busy" | "retry" }
          const statusType = props.status?.type;
          const eventMap = {
            busy:  "UserPromptSubmit",
            // "retry" means OpenCode is re-attempting a request — still THINKING,
            // same state transition as "busy".
            retry: "UserPromptSubmit",
          };
          const hookEvent = eventMap[statusType];
          if (!hookEvent) break;
          await notify({
            source: "opencode",
            hook_event_name: hookEvent,
            session_id: sessionID,
            cwd: sessionDirs.get(sessionID) ?? directory ?? "",
          });
          break;
        }

        case "session.error": {
          const sessionID = props.sessionID;
          if (!sessionID) break;
          await notify({
            source: "opencode",
            hook_event_name: "StopFailure",
            session_id: sessionID,
            cwd: sessionDirs.get(sessionID) ?? directory ?? "",
          });
          break;
        }

        case "permission.updated": {
          const sessionID = props.sessionID;
          if (!sessionID) break;
          await notify({
            source: "opencode",
            hook_event_name: "PermissionRequest",
            session_id: sessionID,
            cwd: sessionDirs.get(sessionID) ?? directory ?? "",
          });
          break;
        }
      }
    },

    // tool.execute.before fires for every tool call — map to TOOL_USE state.
    // OpenCode awaits this hook before running the tool, so we:
    //   1. notify PreToolUse  (display -> TOOL_USE)
    //   2. wait 250ms so the daemon's sync loop has time to push TOOL_USE to
    //      the ESP32 before the tool runs and PostToolUse immediately follows
    //   3. return (tool runs)
    //   4. notify PostToolUse (display -> THINKING)
    // Without the delay, fast tools (file writes, edits) complete before the
    // BLE sync fires and the TOOL_USE animation is never seen.
    "tool.execute.before": async (input) => {
      const sessionID = input.sessionID;
      if (!sessionID) return;
      const cwd = sessionDirs.get(sessionID) ?? directory ?? "";

      await notify({
        source: "opencode",
        hook_event_name: "PreToolUse",
        session_id: sessionID,
        cwd,
      });

      // Give the daemon's sync loop (50ms interval) time to push TOOL_USE
      // to the ESP32 before the tool executes and PostToolUse follows.
      await new Promise((r) => setTimeout(r, 250));
    },

    // tool.execute.after fires once the tool has finished — snap back to THINKING.
    // Note: OpenCode has no PostToolUseFailure equivalent in its event set, so both
    // success and failure land here and both transition the display back to THINKING.
    "tool.execute.after": async (input) => {
      const sessionID = input.sessionID;
      if (!sessionID) return;
      await notify({
        source: "opencode",
        hook_event_name: "PostToolUse",
        session_id: sessionID,
        cwd: sessionDirs.get(sessionID) ?? directory ?? "",
      });
    },
  };
};
