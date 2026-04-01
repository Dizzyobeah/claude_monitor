"""Main daemon: ties together HTTP server, BLE client, and session tracking."""

import asyncio
import logging
import os
import sys
import time
from collections.abc import Coroutine
from typing import Any, NamedTuple

from aiohttp import web

from .ble_manager import BleManager
from .ble_multi import BleMultiManager
from .config import Config
from .http_server import create_app
from .protocol import make_ping_msg, make_remove_msg, make_state_msg, short_sid
from .session_tracker import SessionTracker
from .terminal_mapper import TerminalMapper
from .window_focus import WindowFocus

log = logging.getLogger(__name__)

SYNC_INTERVAL_FAST = 0.05  # seconds — 20 Hz during active states (THINKING, TOOL_USE)
SYNC_INTERVAL_SLOW = 0.50  # seconds — 2 Hz when idle or no sessions
# States that indicate active processing — sync loop polls at SYNC_INTERVAL_FAST
ACTIVE_STATES = {"THINKING", "TOOL_USE", "PERMISSION", "ERROR"}
PING_INTERVAL = 30.0  # seconds between keepalive pings to the ESP32
WATCHDOG_TIMEOUT = 10.0  # seconds — if sync loop hasn't run in this long, exit and let hook auto-restart

# How long a state must be stable before sending to the ESP32.
# Rapid THINKING→TOOL_USE→THINKING transitions (from PreToolUse/PostToolUse) fire
# within ~50ms of each other and fill the ESP32's single-slot _rxBuf before it can
# drain them, causing the screen to always show the dropped intermediate state.
# Holding updates for this many seconds collapses those bursts to the final value.
# Attention-needing states (PERMISSION, INPUT, ERROR) bypass this delay entirely.
SEND_DEBOUNCE_S = 0.15

# States that must be sent immediately, without debounce.
URGENT_STATES = {"PERMISSION", "INPUT", "ERROR"}


class _PendingEntry(NamedTuple):
    """Debounce state for a session waiting to be sent to the ESP32."""
    state: str
    label: str
    idx: int
    total: int
    first_seen_at: float


class ClaudeMonitorDaemon:
    def __init__(self, config: Config):
        self.config = config
        self.tracker = SessionTracker(stale_timeout=config.stale_timeout)
        self.ble: BleManager | BleMultiManager = (
            BleMultiManager(config.max_devices) if config.max_devices > 1 else BleManager()
        )
        self.terminal_mapper = TerminalMapper()
        self.window_focus = WindowFocus()
        # Set by _send_full_state (ready/reconnect) to force _sync_loop to
        # resend all sessions on the next tick, ensuring the display is in sync
        # even if the initial _send_full_state write was dropped.
        self._force_resync: bool = False
        self._shutting_down: bool = False
        # Monotonic heartbeat updated by _sync_loop on every iteration.
        # If _housekeeping_loop detects this hasn't advanced in WATCHDOG_TIMEOUT,
        # the daemon exits so the hook script can auto-restart a fresh process.
        self._sync_heartbeat: float = time.monotonic()
        # Event to wake the sync loop immediately when state changes,
        # instead of waiting for the next poll interval.
        self._sync_wake: asyncio.Event = asyncio.Event()
        # Set True during OTA to pause the sync-loop watchdog.
        self._ota_in_progress: bool = False

    async def run(self) -> None:
        """Start all daemon components as independent tasks."""
        log.info("Claude Monitor daemon starting...")
        log.info("  Hook HTTP port: %d", self.config.http_port)
        log.info("  Display:        BLE (auto-scan)")

        tasks = [
            asyncio.create_task(self._run_http(), name="http"),
            asyncio.create_task(
                self.ble.run(on_message=self._handle_esp32_message), name="ble"
            ),
            asyncio.create_task(self._sync_loop(), name="sync"),
            asyncio.create_task(self._housekeeping_loop(), name="housekeeping"),
            asyncio.create_task(self._ping_loop(), name="ping"),
        ]

        # Run all tasks; if one dies unexpectedly, log and restart it
        while True:
            done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED
            )
            # If housekeeping triggered shutdown, don't restart anything
            if self._shutting_down:
                for t in pending:
                    if not t.done():
                        t.cancel()
                return
            for task in done:
                name = task.get_name()
                exc = task.exception() if not task.cancelled() else None
                if exc:
                    log.error("Task '%s' crashed: %s — restarting in 3s", name, exc)
                else:
                    log.warning("Task '%s' exited cleanly — restarting in 3s", name)
                await asyncio.sleep(3)
                new_task = asyncio.create_task(self._task_for(name), name=name)
                tasks = [t for t in pending] + [new_task]

    def _task_for(self, name: str) -> "Coroutine[Any, Any, None]":
        if name == "http":
            return self._run_http()
        if name == "ble":
            return self.ble.run(on_message=self._handle_esp32_message)
        if name == "sync":
            return self._sync_loop()
        if name == "housekeeping":
            return self._housekeeping_loop()
        if name == "ping":
            return self._ping_loop()
        raise ValueError(f"Unknown task name: {name}")

    async def _run_http(self) -> None:
        """Run the aiohttp server for hook events."""
        app = create_app(self.tracker, ble=self.ble)
        app["sync_wake"] = self._sync_wake
        app["daemon"] = self
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", self.config.http_port)
        await site.start()
        log.info(
            "Hook HTTP server listening on http://127.0.0.1:%d", self.config.http_port
        )
        try:
            await asyncio.Event().wait()
        finally:
            # Ensure the aiohttp server is torn down cleanly on cancellation or restart.
            await runner.cleanup()

    async def _sync_loop(self) -> None:
        """Periodically sync session state to the ESP32.

        A per-session debounce (SEND_DEBOUNCE_S) prevents the ESP32's single-slot
        _rxBuf from being overwritten by rapid THINKING↔TOOL_USE bursts before
        loop() can drain it.  Urgent states (PERMISSION, INPUT, ERROR) bypass the
        debounce so attention-needing transitions always show immediately.

        The poll rate adapts: SYNC_INTERVAL_FAST (50ms) during active states or
        pending debounce, SYNC_INTERVAL_SLOW (500ms) when idle. The _sync_wake
        event allows immediate wake on state change regardless of interval.
        """
        # last_snapshot: what we last *sent* to the ESP32 for each session.
        last_snapshot: dict[str, tuple[str, str, int, int]] = {}
        # pending: candidate values not yet sent, waiting to stabilise.
        pending: dict[str, _PendingEntry] = {}
        # Track previous connected state so we can detect reconnection.
        was_connected: bool = False
        interval: float = SYNC_INTERVAL_FAST

        while True:
            # Wait for the poll interval, but wake early if state changed.
            # Using wait_for on the event gives us adaptive polling without
            # busy-waiting: fast (50ms) during active states, slow (500ms) idle.
            self._sync_wake.clear()
            try:
                await asyncio.wait_for(self._sync_wake.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
            self._sync_heartbeat = time.monotonic()

            currently_connected = self.ble.connected

            if not currently_connected:
                last_snapshot.clear()
                pending.clear()
                was_connected = False
                continue

            # On the transition from disconnected → connected, force a full resync
            # regardless of whether a 'ready' event arrives.  The 'ready' path is
            # the normal case, but the notification can be dropped (e.g. during MTU
            # negotiation) leaving the display stuck on "No active sessions" even
            # though the daemon has sessions in its tracker.
            if not was_connected:
                was_connected = True
                last_snapshot.clear()
                pending.clear()

            # After a ready/reconnect event, clear the snapshot so we resend
            # everything — the initial _send_full_state write may have been
            # dropped if the connection was still settling.
            if self._force_resync:
                self._force_resync = False
                last_snapshot.clear()
                pending.clear()

            # Process deferred session removals so the grace period is
            # honoured promptly (housekeeping only runs every 30s).
            self.tracker.prune_stale()

            # Collect all outgoing messages and send them in one BLE write.
            # The firmware's _rxBuf is a single-slot buffer: if the daemon sends
            # multiple writes back-to-back, each write overwrites the previous one
            # before the ESP32's loop() can drain it.  Batching into one newline-
            # separated payload avoids that race entirely.
            batch: list[str] = []

            # Remove messages for sessions that ended since last sync
            removed_ids = self.tracker.pop_removed_ids()
            for removed_id in removed_ids:
                log.debug("Sending remove for session %s", removed_id)
                batch.append(make_remove_msg(removed_id).rstrip("\n"))
                last_snapshot.pop(removed_id, None)
                pending.pop(removed_id, None)

            sessions = self.tracker.get_ordered_sessions()
            total = len(sessions)
            now = time.monotonic()

            for idx, info in enumerate(sessions):
                key = info.session_id
                snapshot = (info.state, info.label, idx, total)

                if last_snapshot.get(key) == snapshot:
                    # Already sent — no change.
                    pending.pop(key, None)
                    continue

                # Urgent states bypass debounce and are sent on the next tick.
                urgent = info.state in URGENT_STATES

                if urgent:
                    pending.pop(key, None)
                    last_snapshot[key] = snapshot
                    batch.append(
                        make_state_msg(
                            sid=info.session_id,
                            state=info.state,
                            label=info.label,
                            idx=idx,
                            total=total,
                        ).rstrip("\n")
                    )
                    continue

                # Non-urgent: record when this value was first seen.
                prev_pending = pending.get(key)
                if prev_pending is None or prev_pending[:4] != snapshot:
                    # New or changed value — start the debounce clock.
                    pending[key] = _PendingEntry(*snapshot, now)
                    continue

                # Same value seen for long enough — ready to send.
                if now - prev_pending.first_seen_at >= SEND_DEBOUNCE_S:
                    pending.pop(key, None)
                    last_snapshot[key] = snapshot
                    batch.append(
                        make_state_msg(
                            sid=info.session_id,
                            state=info.state,
                            label=info.label,
                            idx=idx,
                            total=total,
                        ).rstrip("\n")
                    )

            if batch:
                log.debug("Sync batch: %d message(s)", len(batch))
                await self.ble.send("\n".join(batch) + "\n")

            # Drop stale snapshot/pending entries for sessions that no longer exist
            active_ids = {s.session_id for s in sessions}
            for gone in set(last_snapshot) - active_ids:
                del last_snapshot[gone]
            for gone in set(pending) - active_ids:
                del pending[gone]

            # Adaptive poll rate: fast when any session is active or debounce pending
            has_active = any(s.state in ACTIVE_STATES for s in sessions)
            interval = SYNC_INTERVAL_FAST if (has_active or pending) else SYNC_INTERVAL_SLOW

    async def _ping_loop(self) -> None:
        """Send periodic keepalive pings to the ESP32 to detect silent disconnects."""
        while True:
            await asyncio.sleep(PING_INTERVAL)
            if self.ble.connected:
                log.debug("Sending ping to ESP32")
                await self.ble.send(make_ping_msg())

    async def _housekeeping_loop(self) -> None:
        """Periodic cleanup. Exits the process when all sessions have ended."""
        while True:
            await asyncio.sleep(30)
            self.tracker.prune_stale()

            # Self-health watchdog: if the sync loop has stalled, exit so the
            # hook script can auto-restart a fresh daemon process.
            # NOTE: sys.exit() raises SystemExit which is swallowed by asyncio
            # tasks — it gets stored as the task exception and the supervisor
            # restarts the task instead of exiting.  os._exit() bypasses all
            # cleanup and terminates the process immediately, which is exactly
            # what a watchdog needs when the event loop is stuck.
            stale = time.monotonic() - self._sync_heartbeat
            if stale > WATCHDOG_TIMEOUT and not self._ota_in_progress:
                log.critical(
                    "Sync loop stalled for %.1fs (limit %.1fs) — exiting for auto-restart",
                    stale, WATCHDOG_TIMEOUT,
                )
                os._exit(1)

            if self.tracker.is_idle:
                log.info("All sessions ended — shutting down.")
                self._shutting_down = True
                return

    async def _handle_esp32_message(self, msg: dict[str, Any]) -> None:
        """Handle messages from the ESP32 (tap, pong, ready)."""
        cmd = msg.get("cmd", "")

        if cmd == "tap":
            await self._handle_tap(msg.get("sid", ""))
        elif cmd == "dictate":
            await self._handle_dictate(msg.get("sid", ""))
        elif cmd == "ready":
            log.info("ESP32 display is ready — sending full state")
            await self._send_full_state()
        elif cmd == "overflow":
            log.warning("ESP32 ring buffer overflow — resending full state")
            await self._send_full_state()
        elif cmd == "pong":
            log.debug("ESP32 pong received")

    async def _handle_tap(self, sid: str) -> None:
        """Handle a touch tap - focus the corresponding terminal window."""
        if not sid:
            return

        for session_id, info in self.tracker.sessions.items():
            if short_sid(session_id) == sid:
                log.info(
                    "Tap on session %s (%s) state=%s ppid=%r tty=%r",
                    sid,
                    info.label,
                    info.state,
                    info.ppid,
                    info.tty,
                )

                # At DEBUG level, dump the full ancestor chain so failures are diagnosable
                if log.isEnabledFor(logging.DEBUG) and info.ppid:
                    try:
                        import psutil

                        p = psutil.Process(int(info.ppid))
                        chain = []
                        ancestor = p
                        for _ in range(15):
                            try:
                                ancestor = ancestor.parent()
                                if ancestor is None:
                                    break
                                exe = ""
                                try:
                                    exe = ancestor.exe()
                                except (psutil.AccessDenied, psutil.NoSuchProcess):
                                    pass
                                chain.append(
                                    f"  pid={ancestor.pid} name={ancestor.name()!r} exe={exe!r}"
                                )
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                chain.append("  <access denied or process gone>")
                                break
                        log.debug(
                            "Ancestor chain for ppid %s:\n%s",
                            info.ppid,
                            "\n".join(chain) if chain else "  (empty)",
                        )
                    except Exception as exc:
                        log.debug("Could not walk ancestor chain: %s", exc)

                # Use cached terminal ref if available; otherwise look it up
                # and cache for subsequent taps on the same session.
                ref = info._cached_terminal
                if ref is None:
                    ref = self.terminal_mapper.find_terminal(
                        ppid=info.ppid,
                        tty=info.tty,
                    )
                    if ref:
                        info._cached_terminal = ref
                if ref:
                    log.info(
                        "Resolved terminal: app=%r app_name=%r pid=%d — focusing",
                        ref.app,
                        ref.app_name,
                        ref.pid,
                    )
                    success = await self.window_focus.focus(ref)
                    if not success:
                        log.warning(
                            "window_focus.focus() returned False for %s (pid %d)",
                            ref.app_name,
                            ref.pid,
                        )
                else:
                    log.warning(
                        "Could not find terminal for session %s "
                        "(ppid=%r tty=%r) — run with -v for ancestor chain",
                        sid,
                        info.ppid,
                        info.tty,
                    )
                return

        log.warning("Tap for unknown session: %s", sid)

    async def _handle_dictate(self, sid: str) -> None:
        """Handle a long-press — focus terminal then trigger macOS dictation."""
        if not sid:
            return

        for session_id, info in self.tracker.sessions.items():
            if short_sid(session_id) == sid:
                log.info("Dictate on session %s (%s)", sid, info.label)

                ref = info._cached_terminal
                if ref is None:
                    ref = self.terminal_mapper.find_terminal(
                        ppid=info.ppid,
                        tty=info.tty,
                    )
                    if ref:
                        info._cached_terminal = ref

                if ref:
                    await self.window_focus.focus(ref)
                    await asyncio.sleep(0.2)  # let window come to front
                    success = await self.window_focus.trigger_dictation()
                    if not success:
                        log.warning("Dictation trigger failed for session %s", sid)
                else:
                    log.warning(
                        "Could not find terminal for dictate session %s "
                        "(ppid=%r tty=%r)",
                        sid,
                        info.ppid,
                        info.tty,
                    )
                return

        log.warning("Dictate for unknown session: %s", sid)

    async def _send_full_state(self) -> None:
        """Send complete session state to ESP32 (called on reconnect/ready)."""
        # Batch everything into a single BLE write — firmware has a single-slot
        # receive buffer so multiple rapid writes would overwrite each other.
        batch: list[str] = []

        # Drain pending removes first
        for removed_id in self.tracker.pop_removed_ids():
            batch.append(make_remove_msg(removed_id).rstrip("\n"))

        sessions = self.tracker.get_ordered_sessions()
        total = len(sessions)
        for idx, info in enumerate(sessions):
            batch.append(
                make_state_msg(
                    sid=info.session_id,
                    state=info.state,
                    label=info.label,
                    idx=idx,
                    total=total,
                ).rstrip("\n")
            )

        if batch:
            await self.ble.send("\n".join(batch) + "\n")

        # Signal the sync loop to clear its snapshot so it resends everything
        # on the next tick — guards against the initial write being dropped
        # while the BLE connection is still settling after a ready event.
        self._force_resync = True
