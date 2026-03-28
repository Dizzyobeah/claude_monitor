"""Tests for ClaudeMonitorDaemon: sync loop, remove messages, ping, task routing."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from claude_monitor.daemon import (
    ClaudeMonitorDaemon,
    PING_INTERVAL,
    SEND_DEBOUNCE_S,
    SYNC_INTERVAL,
    URGENT_STATES,
)
from claude_monitor.config import Config
from claude_monitor.session_tracker import SessionTracker
from claude_monitor.protocol import make_remove_msg, make_ping_msg, short_sid
from claude_monitor.terminal_mapper import WindowRef


def make_daemon(verbose: bool = False) -> ClaudeMonitorDaemon:
    config = Config(http_port=7483, stale_timeout=600, verbose=verbose)
    daemon = ClaudeMonitorDaemon(config)
    # Replace BleManager with a mock
    daemon.ble = MagicMock()
    daemon.ble.connected = True
    daemon.ble.send = AsyncMock()
    return daemon


# ---------------------------------------------------------------------------
# _sync_loop: remove messages
# ---------------------------------------------------------------------------


class TestSyncLoopRemoveMessages:
    @pytest.mark.asyncio
    async def test_remove_message_sent_when_session_ends(self):
        daemon = make_daemon()
        # Pre-populate with one session then end it; force-expire the grace period
        daemon.tracker.update_session("sess1", "SessionStart", {})
        daemon.tracker.update_session("sess1", "SessionEnd", {})
        # Expire the grace period immediately so pop_removed_ids returns it
        daemon.tracker._remove_session("sess1")

        # Run exactly one sync tick
        async def one_tick():
            await asyncio.sleep(SYNC_INTERVAL * 1.1)

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            # We only want one iteration; make the second sleep raise CancelledError
            call_count = 0

            async def sleep_side_effect(t):
                nonlocal call_count
                call_count += 1
                if call_count > 1:
                    raise asyncio.CancelledError()

            mock_sleep.side_effect = sleep_side_effect

            try:
                await daemon._sync_loop()
            except asyncio.CancelledError:
                pass

        # The remove message should have been sent
        sent_calls = [c.args[0] for c in daemon.ble.send.call_args_list]
        assert make_remove_msg("sess1") in sent_calls

    @pytest.mark.asyncio
    async def test_no_remove_message_when_no_session_ended(self):
        daemon = make_daemon()
        daemon.tracker.update_session("sess1", "SessionStart", {})

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            call_count = 0

            async def sleep_side_effect(t):
                nonlocal call_count
                call_count += 1
                if call_count > 1:
                    raise asyncio.CancelledError()

            mock_sleep.side_effect = sleep_side_effect

            try:
                await daemon._sync_loop()
            except asyncio.CancelledError:
                pass

        sent_calls = [c.args[0] for c in daemon.ble.send.call_args_list]
        assert make_remove_msg("sess1") not in sent_calls

    @pytest.mark.asyncio
    async def test_remove_message_not_sent_when_disconnected(self):
        daemon = make_daemon()
        daemon.ble.connected = False
        daemon.tracker.update_session("sess1", "SessionStart", {})
        daemon.tracker.update_session("sess1", "SessionEnd", {})

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            call_count = 0

            async def sleep_side_effect(t):
                nonlocal call_count
                call_count += 1
                if call_count > 1:
                    raise asyncio.CancelledError()

            mock_sleep.side_effect = sleep_side_effect

            try:
                await daemon._sync_loop()
            except asyncio.CancelledError:
                pass

        daemon.ble.send.assert_not_called()


# ---------------------------------------------------------------------------
# _sync_loop: debounce — non-urgent states held back until stable
# ---------------------------------------------------------------------------


class TestSyncLoopDebounce:
    """Verify that non-urgent states are held back by SEND_DEBOUNCE_S."""

    def _run_n_ticks(self, daemon, n: int, monotonic_offset: float = 0.0):
        """Run the sync loop for exactly n ticks, with time.monotonic advancing
        by SYNC_INTERVAL per tick plus an optional extra offset on the first tick."""
        import time

        tick_count = 0
        base_time = time.monotonic()

        async def sleep_side_effect(t):
            nonlocal tick_count
            tick_count += 1
            if tick_count > n:
                raise asyncio.CancelledError()

        monotonic_calls = [0]

        def fake_monotonic():
            return base_time + monotonic_offset + tick_count * SYNC_INTERVAL

        return sleep_side_effect, fake_monotonic

    @pytest.mark.asyncio
    async def test_non_urgent_state_not_sent_immediately(self):
        """THINKING (non-urgent) should not be sent on the first tick."""
        from claude_monitor.protocol import make_state_msg

        daemon = make_daemon()
        daemon.tracker.update_session("sess1", "UserPromptSubmit", {"cwd": "/proj"})
        assert daemon.tracker.sessions["sess1"].state == "THINKING"

        import time

        base = time.monotonic()
        tick = [0]

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with patch(
                "time.monotonic", side_effect=lambda: base + tick[0] * SYNC_INTERVAL
            ):

                async def sleep_se(t):
                    tick[0] += 1
                    if tick[0] > 1:
                        raise asyncio.CancelledError()

                mock_sleep.side_effect = sleep_se
                try:
                    await daemon._sync_loop()
                except asyncio.CancelledError:
                    pass

        # THINKING is non-urgent: nothing should have been sent on tick 1
        daemon.ble.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_urgent_state_sent_after_debounce(self):
        """THINKING should be sent once it has been stable for SEND_DEBOUNCE_S."""
        from claude_monitor.protocol import make_state_msg

        daemon = make_daemon()
        daemon.tracker.update_session("sess1", "UserPromptSubmit", {"cwd": "/proj"})

        import time

        base = time.monotonic()
        tick = [0]
        # advance time by enough to clear the debounce (+3 accounts for
        # the was_connected tick, the debounce itself, and float rounding)
        debounce_ticks = round(SEND_DEBOUNCE_S / SYNC_INTERVAL) + 3

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with patch(
                "time.monotonic",
                side_effect=lambda: base + tick[0] * SYNC_INTERVAL,
            ):

                async def sleep_se(t):
                    tick[0] += 1
                    if tick[0] > debounce_ticks:
                        raise asyncio.CancelledError()

                mock_sleep.side_effect = sleep_se
                try:
                    await daemon._sync_loop()
                except asyncio.CancelledError:
                    pass

        sent = [c.args[0] for c in daemon.ble.send.call_args_list]
        expected = make_state_msg(
            sid="sess1", state="THINKING", label="proj", idx=0, total=1
        )
        assert expected in sent

    @pytest.mark.asyncio
    async def test_urgent_state_sent_immediately(self):
        """INPUT (urgent) should be sent on the very first tick after connection."""
        from claude_monitor.protocol import make_state_msg

        for state_event, expected_state in [
            ("SessionStart", "INPUT"),
            ("PermissionRequest", "PERMISSION"),
        ]:
            daemon = make_daemon()
            daemon.tracker.update_session("sess1", state_event, {"cwd": "/proj"})

            import time

            base = time.monotonic()
            tick = [0]

            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                with patch(
                    "time.monotonic", side_effect=lambda: base + tick[0] * SYNC_INTERVAL
                ):

                    async def sleep_se(t):
                        tick[0] += 1
                        if tick[0] > 1:
                            raise asyncio.CancelledError()

                    mock_sleep.side_effect = sleep_se
                    try:
                        await daemon._sync_loop()
                    except asyncio.CancelledError:
                        pass

            sent = [c.args[0] for c in daemon.ble.send.call_args_list]
            expected = make_state_msg(
                sid="sess1", state=expected_state, label="proj", idx=0, total=1
            )
            assert expected in sent, f"{expected_state} should bypass debounce"


class TestSendFullState:
    @pytest.mark.asyncio
    async def test_pending_removes_sent_on_full_state(self):
        daemon = make_daemon()
        daemon.tracker.update_session("sess1", "SessionStart", {})
        daemon.tracker.update_session("sess1", "SessionEnd", {})
        # Expire grace period so the session is queued for removal
        daemon.tracker._remove_session("sess1")

        await daemon._send_full_state()

        sent_calls = [c.args[0] for c in daemon.ble.send.call_args_list]
        assert make_remove_msg("sess1") in sent_calls

    @pytest.mark.asyncio
    async def test_active_sessions_sent_on_full_state(self):
        from claude_monitor.protocol import make_state_msg

        daemon = make_daemon()
        daemon.tracker.update_session(
            "sess1", "SessionStart", {"cwd": "/home/user/proj"}
        )

        await daemon._send_full_state()

        sent_calls = [c.args[0] for c in daemon.ble.send.call_args_list]
        expected = make_state_msg(
            sid="sess1", state="INPUT", label="proj", idx=0, total=1
        )
        assert expected in sent_calls


# ---------------------------------------------------------------------------
# _housekeeping_loop: auto-exit when all sessions end
# ---------------------------------------------------------------------------


class TestHousekeepingLoop:
    @pytest.mark.asyncio
    async def test_loop_stops_when_tracker_is_idle(self):
        """After all sessions end, _housekeeping_loop sets _shutting_down and returns."""
        daemon = make_daemon()
        daemon.tracker.update_session("s1", "SessionStart", {})
        # Force the session fully removed so is_idle becomes True
        daemon.tracker._remove_session("s1")
        assert daemon.tracker.is_idle
        assert not daemon._shutting_down

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            call_count = 0

            async def sleep_side_effect(t):
                nonlocal call_count
                call_count += 1
                if call_count > 1:
                    raise asyncio.CancelledError()

            mock_sleep.side_effect = sleep_side_effect

            # Should return cleanly (not raise CancelledError)
            await daemon._housekeeping_loop()

            # The daemon should be flagged for shutdown
            assert daemon._shutting_down

    @pytest.mark.asyncio
    async def test_loop_does_not_stop_on_cold_start(self):
        """Daemon must not auto-exit if no session was ever seen."""
        daemon = make_daemon()
        # No sessions ever added — is_idle is False

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            call_count = 0

            async def sleep_side_effect(t):
                nonlocal call_count
                call_count += 1
                if call_count > 1:
                    raise asyncio.CancelledError()

            mock_sleep.side_effect = sleep_side_effect

            with (
                patch("asyncio.all_tasks") as mock_all_tasks,
                patch("asyncio.current_task") as mock_current_task,
            ):
                current = MagicMock(name="current_task")
                mock_current_task.return_value = current
                mock_all_tasks.return_value = [current]
                try:
                    await daemon._housekeeping_loop()
                except asyncio.CancelledError:
                    pass
                # No tasks should be cancelled — is_idle is False
                current.cancel.assert_not_called()


# ---------------------------------------------------------------------------
# _ping_loop
# ---------------------------------------------------------------------------


class TestPingLoop:
    @pytest.mark.asyncio
    async def test_ping_sent_when_connected(self):
        daemon = make_daemon()
        daemon.ble.connected = True

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            call_count = 0

            async def sleep_side_effect(t):
                nonlocal call_count
                call_count += 1
                if call_count > 1:
                    raise asyncio.CancelledError()

            mock_sleep.side_effect = sleep_side_effect

            try:
                await daemon._ping_loop()
            except asyncio.CancelledError:
                pass

        daemon.ble.send.assert_called_once_with(make_ping_msg())

    @pytest.mark.asyncio
    async def test_ping_not_sent_when_disconnected(self):
        daemon = make_daemon()
        daemon.ble.connected = False

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            call_count = 0

            async def sleep_side_effect(t):
                nonlocal call_count
                call_count += 1
                if call_count > 1:
                    raise asyncio.CancelledError()

            mock_sleep.side_effect = sleep_side_effect

            try:
                await daemon._ping_loop()
            except asyncio.CancelledError:
                pass

        daemon.ble.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_ping_uses_correct_interval(self):
        daemon = make_daemon()

        slept_durations = []

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            call_count = 0

            async def sleep_side_effect(t):
                nonlocal call_count
                slept_durations.append(t)
                call_count += 1
                if call_count >= 1:
                    raise asyncio.CancelledError()

            mock_sleep.side_effect = sleep_side_effect

            try:
                await daemon._ping_loop()
            except asyncio.CancelledError:
                pass

        assert slept_durations[0] == PING_INTERVAL


# ---------------------------------------------------------------------------
# _task_for routing
# ---------------------------------------------------------------------------


class TestTaskFor:
    def test_all_known_task_names_return_coroutines(self):
        daemon = make_daemon()

        # Give BLE a real async run method so _task_for("ble") returns a coroutine
        async def _fake_ble_run(on_message):
            pass

        daemon.ble.run = _fake_ble_run

        for name in ("http", "ble", "sync", "housekeeping", "ping"):
            coro = daemon._task_for(name)
            assert asyncio.iscoroutine(coro), f"Expected coroutine for task '{name}'"
            coro.close()  # prevent ResourceWarning

    def test_unknown_task_name_raises(self):
        daemon = make_daemon()
        with pytest.raises(ValueError):
            daemon._task_for("nonexistent")


# ---------------------------------------------------------------------------
# _handle_esp32_message routing
# ---------------------------------------------------------------------------


class TestHandleEsp32Message:
    @pytest.mark.asyncio
    async def test_ready_triggers_full_state(self):
        daemon = make_daemon()
        with patch.object(
            daemon, "_send_full_state", new_callable=AsyncMock
        ) as mock_send:
            await daemon._handle_esp32_message({"cmd": "ready"})
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_tap_triggers_handle_tap(self):
        daemon = make_daemon()
        with patch.object(daemon, "_handle_tap", new_callable=AsyncMock) as mock_tap:
            await daemon._handle_esp32_message({"cmd": "tap", "sid": "abc12"})
            mock_tap.assert_called_once_with("abc12")

    @pytest.mark.asyncio
    async def test_pong_is_handled_silently(self):
        daemon = make_daemon()
        # Should not raise and should not call BLE send
        await daemon._handle_esp32_message({"cmd": "pong"})
        daemon.ble.send.assert_not_called()


# ---------------------------------------------------------------------------
# _handle_tap
# ---------------------------------------------------------------------------


class TestHandleTap:
    @pytest.mark.asyncio
    async def test_tap_focuses_found_terminal(self):
        """When find_terminal returns a WindowRef, focus() is called with it."""
        daemon = make_daemon()
        daemon.tracker.update_session(
            "abcde12345", "SessionStart", {"cwd": "/home/user/proj"}
        )
        # Manually set ppid/tty on the tracked session
        daemon.tracker.sessions["abcde12345"].ppid = "1234"
        daemon.tracker.sessions["abcde12345"].tty = "/dev/ttys001"

        ref = WindowRef(app="iterm2", app_name="iTerm2", pid=999)
        daemon.terminal_mapper = MagicMock()
        daemon.terminal_mapper.find_terminal.return_value = ref

        daemon.window_focus = MagicMock()
        daemon.window_focus.focus = AsyncMock(return_value=True)

        await daemon._handle_tap(short_sid("abcde12345"))

        daemon.terminal_mapper.find_terminal.assert_called_once_with(
            ppid="1234", tty="/dev/ttys001"
        )
        daemon.window_focus.focus.assert_called_once_with(ref)

    @pytest.mark.asyncio
    async def test_tap_logs_warning_when_terminal_not_found(self):
        """When find_terminal returns None, no exception is raised and focus is not called."""
        daemon = make_daemon()
        daemon.tracker.update_session("fffff12345", "SessionStart", {})
        daemon.tracker.sessions["fffff12345"].ppid = "5678"
        daemon.tracker.sessions["fffff12345"].tty = ""

        daemon.terminal_mapper = MagicMock()
        daemon.terminal_mapper.find_terminal.return_value = None

        daemon.window_focus = MagicMock()
        daemon.window_focus.focus = AsyncMock(return_value=False)

        # Must not raise
        await daemon._handle_tap(short_sid("fffff12345"))

        daemon.window_focus.focus.assert_not_called()

    @pytest.mark.asyncio
    async def test_tap_unknown_sid_does_not_raise(self):
        """A tap for an unknown session id is silently ignored (just a warning log)."""
        daemon = make_daemon()
        daemon.terminal_mapper = MagicMock()
        daemon.window_focus = MagicMock()
        daemon.window_focus.focus = AsyncMock()

        await daemon._handle_tap("zzzzz")

        daemon.window_focus.focus.assert_not_called()

    @pytest.mark.asyncio
    async def test_tap_empty_sid_returns_immediately(self):
        """Empty sid is a no-op."""
        daemon = make_daemon()
        daemon.terminal_mapper = MagicMock()
        daemon.window_focus = MagicMock()
        daemon.window_focus.focus = AsyncMock()

        await daemon._handle_tap("")

        daemon.terminal_mapper.find_terminal.assert_not_called()
        daemon.window_focus.focus.assert_not_called()

    @pytest.mark.asyncio
    async def test_tap_focus_returns_false_no_exception(self):
        """If focus() returns False we log a warning but don't raise."""
        daemon = make_daemon()
        daemon.tracker.update_session("11111aaaaa", "SessionStart", {})
        daemon.tracker.sessions["11111aaaaa"].ppid = "9999"
        daemon.tracker.sessions["11111aaaaa"].tty = ""

        ref = WindowRef(app="code", app_name="VS Code", pid=777)
        daemon.terminal_mapper = MagicMock()
        daemon.terminal_mapper.find_terminal.return_value = ref

        daemon.window_focus = MagicMock()
        daemon.window_focus.focus = AsyncMock(return_value=False)

        await daemon._handle_tap(short_sid("11111aaaaa"))  # Must not raise

        daemon.window_focus.focus.assert_called_once_with(ref)
