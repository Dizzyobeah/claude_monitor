"""Main daemon: ties together HTTP server, BLE client, and session tracking."""

import asyncio
import logging

from aiohttp import web

from .config import Config
from .http_server import create_app
from .ble_manager import BleManager
from .session_tracker import SessionTracker
from .terminal_mapper import TerminalMapper
from .window_focus import WindowFocus
from .protocol import make_state_msg, make_remove_msg

log = logging.getLogger(__name__)


class ClaudeMonitorDaemon:
    def __init__(self, config: Config):
        self.config = config
        self.tracker = SessionTracker(stale_timeout=config.stale_timeout)
        self.ble = BleManager()
        self.terminal_mapper = TerminalMapper()
        self.window_focus = WindowFocus()

    async def run(self) -> None:
        """Start all daemon components."""
        log.info("Claude Monitor daemon starting...")
        log.info("  Hook HTTP port: %d", self.config.http_port)
        log.info("  Display:        BLE (auto-scan)")

        await asyncio.gather(
            self._run_http(),
            self.ble.run(on_message=self._handle_esp32_message),
            self._sync_loop(),
            self._housekeeping_loop(),
        )

    async def _run_http(self) -> None:
        """Run the aiohttp server for hook events."""
        app = create_app(self.tracker)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", self.config.http_port)
        await site.start()
        log.info("Hook HTTP server listening on http://127.0.0.1:%d", self.config.http_port)
        await asyncio.Event().wait()

    async def _sync_loop(self) -> None:
        """Periodically sync session state to the ESP32."""
        while True:
            await asyncio.sleep(0.1)  # 10Hz sync rate

            if not self.ble.connected:
                continue

            sessions = self.tracker.get_ordered_sessions()
            total = len(sessions)

            if total == 0:
                continue

            for idx, info in enumerate(sessions):
                msg = make_state_msg(
                    sid=info.session_id,
                    state=info.state,
                    label=info.label,
                    idx=idx,
                    total=total,
                )
                await self.ble.send(msg)

    async def _housekeeping_loop(self) -> None:
        """Periodic cleanup."""
        while True:
            await asyncio.sleep(30)
            self.tracker.prune_stale()

    async def _handle_esp32_message(self, msg: dict) -> None:
        """Handle messages from the ESP32 (tap, pong, ready)."""
        cmd = msg.get("cmd", "")

        if cmd == "tap":
            await self._handle_tap(msg.get("sid", ""))
        elif cmd == "ready":
            log.info("ESP32 display is ready")
            await self._send_full_state()
        elif cmd == "pong":
            log.debug("ESP32 pong received")

    async def _handle_tap(self, sid: str) -> None:
        """Handle a touch tap - focus the corresponding terminal window."""
        if not sid:
            return

        for session_id, info in self.tracker.sessions.items():
            if session_id[:5] == sid:
                log.info("Tap on session %s (%s) - focusing terminal", sid, info.label)
                ref = self.terminal_mapper.find_terminal(
                    ppid=info.ppid,
                    tty=info.tty,
                )
                if ref:
                    await self.window_focus.focus(ref)
                else:
                    log.warning("Could not find terminal for session %s", sid)
                return

        log.warning("Tap for unknown session: %s", sid)

    async def _send_full_state(self) -> None:
        """Send complete session state to ESP32."""
        sessions = self.tracker.get_ordered_sessions()
        total = len(sessions)
        for idx, info in enumerate(sessions):
            msg = make_state_msg(
                sid=info.session_id,
                state=info.state,
                label=info.label,
                idx=idx,
                total=total,
            )
            await self.ble.send(msg)
