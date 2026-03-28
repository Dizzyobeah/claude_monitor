"""Tests for WindowFocus: platform-appropriate terminal window activation."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from claude_monitor.window_focus import WindowFocus
from claude_monitor.terminal_mapper import WindowRef


def _ref(app="iterm2", app_name="iTerm2", pid=1234):
    return WindowRef(app=app, app_name=app_name, pid=pid)


# ---------------------------------------------------------------------------
# Helper: build a fake subprocess result
# ---------------------------------------------------------------------------


def _fake_proc(returncode: int, stdout: bytes = b"", stderr: bytes = b""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


# ---------------------------------------------------------------------------
# _build_applescript
# ---------------------------------------------------------------------------


class TestBuildApplescript:
    def test_iterm2(self):
        wf = WindowFocus()
        script = wf._build_applescript(_ref(app="iterm2", app_name="iTerm2"))
        assert 'application "iTerm2"' in script
        assert "activate" in script

    def test_terminal(self):
        wf = WindowFocus()
        script = wf._build_applescript(_ref(app="terminal", app_name="Terminal"))
        assert 'application "Terminal"' in script
        assert "set index of front window to 1" in script

    @pytest.mark.parametrize(
        "app,app_name",
        [
            ("warp", "Warp"),
            ("alacritty", "Alacritty"),
            ("kitty", "kitty"),
            ("wezterm-gui", "WezTerm"),
            ("ghostty", "Ghostty"),
        ],
    )
    def test_generic_activate(self, app, app_name):
        wf = WindowFocus()
        script = wf._build_applescript(_ref(app=app, app_name=app_name))
        assert f'application "{app_name}"' in script
        assert "activate" in script

    def test_unknown_app_uses_system_events_pid_fallback(self):
        wf = WindowFocus()
        script = wf._build_applescript(_ref(app="cursor", app_name="Cursor", pid=9999))
        assert "System Events" in script
        assert "9999" in script
        assert "unix id" in script


# ---------------------------------------------------------------------------
# _focus_macos
# ---------------------------------------------------------------------------


class TestFocusMacos:
    @pytest.mark.asyncio
    async def test_success_returns_true(self):
        wf = WindowFocus()
        proc = _fake_proc(returncode=0)
        with patch(
            "claude_monitor.window_focus.asyncio.create_subprocess_exec",
            return_value=proc,
        ):
            result = await wf._focus_macos(_ref())
        assert result is True

    @pytest.mark.asyncio
    async def test_nonzero_returncode_returns_false(self):
        wf = WindowFocus()
        proc = _fake_proc(returncode=1, stderr=b"execution error")
        with patch(
            "claude_monitor.window_focus.asyncio.create_subprocess_exec",
            return_value=proc,
        ):
            result = await wf._focus_macos(_ref())
        assert result is False

    @pytest.mark.asyncio
    async def test_timeout_returns_false(self):
        wf = WindowFocus()
        proc = MagicMock()
        proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        with patch(
            "claude_monitor.window_focus.asyncio.create_subprocess_exec",
            return_value=proc,
        ):
            result = await wf._focus_macos(_ref())
        assert result is False

    @pytest.mark.asyncio
    async def test_file_not_found_returns_false(self):
        wf = WindowFocus()
        with patch(
            "claude_monitor.window_focus.asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError(),
        ):
            result = await wf._focus_macos(_ref())
        assert result is False

    @pytest.mark.asyncio
    async def test_no_script_returns_false(self):
        """_focus_macos returns False when _build_applescript returns empty string."""
        wf = WindowFocus()
        with patch.object(wf, "_build_applescript", return_value=""):
            result = await wf._focus_macos(_ref())
        assert result is False


# ---------------------------------------------------------------------------
# _focus_windows
# ---------------------------------------------------------------------------


class TestFocusWindows:
    @pytest.mark.asyncio
    async def test_success_when_hwnd_found(self):
        wf = WindowFocus()
        fake_hwnd = 0xABCD

        async def fake_executor(_executor, fn, *args):
            # First call returns the hwnd; second call returns True (focus success)
            if fn == wf._find_hwnd_for_pid:
                return fake_hwnd
            if fn == wf._set_foreground_attached:
                return True
            return None

        loop = MagicMock()
        loop.run_in_executor = AsyncMock(side_effect=fake_executor)

        with patch(
            "claude_monitor.window_focus.asyncio.get_running_loop", return_value=loop
        ):
            result = await wf._focus_windows(_ref())
        assert result is True

    @pytest.mark.asyncio
    async def test_no_hwnd_returns_false(self):
        wf = WindowFocus()

        async def fake_executor(_executor, fn, *args):
            if fn == wf._find_hwnd_for_pid:
                return None
            return True

        loop = MagicMock()
        loop.run_in_executor = AsyncMock(side_effect=fake_executor)

        with patch(
            "claude_monitor.window_focus.asyncio.get_running_loop", return_value=loop
        ):
            result = await wf._focus_windows(_ref())
        assert result is False

    @pytest.mark.asyncio
    async def test_exception_returns_false(self):
        wf = WindowFocus()
        loop = MagicMock()
        loop.run_in_executor = AsyncMock(side_effect=RuntimeError("ctypes error"))

        with patch(
            "claude_monitor.window_focus.asyncio.get_running_loop", return_value=loop
        ):
            result = await wf._focus_windows(_ref())
        assert result is False


# ---------------------------------------------------------------------------
# _focus_linux — try-chain
# ---------------------------------------------------------------------------


class TestFocusLinux:
    @pytest.mark.asyncio
    async def test_wmctrl_success(self):
        wf = WindowFocus()
        m_wmctrl = AsyncMock(return_value=True)
        m_xdotool = AsyncMock(return_value=False)
        m_swaymsg = AsyncMock(return_value=False)
        m_ydotool = AsyncMock(return_value=False)
        with (
            patch.object(wf, "_try_wmctrl", m_wmctrl),
            patch.object(wf, "_try_xdotool", m_xdotool),
            patch.object(wf, "_try_swaymsg", m_swaymsg),
            patch.object(wf, "_try_ydotool", m_ydotool),
        ):
            result = await wf._focus_linux(_ref())
        assert result is True
        m_wmctrl.assert_called_once_with(_ref().pid)
        m_xdotool.assert_not_called()

    @pytest.mark.asyncio
    async def test_xdotool_fallback(self):
        wf = WindowFocus()
        m_wmctrl = AsyncMock(return_value=False)
        m_xdotool = AsyncMock(return_value=True)
        m_swaymsg = AsyncMock(return_value=False)
        m_ydotool = AsyncMock(return_value=False)
        with (
            patch.object(wf, "_try_wmctrl", m_wmctrl),
            patch.object(wf, "_try_xdotool", m_xdotool),
            patch.object(wf, "_try_swaymsg", m_swaymsg),
            patch.object(wf, "_try_ydotool", m_ydotool),
        ):
            result = await wf._focus_linux(_ref())
        assert result is True
        m_swaymsg.assert_not_called()

    @pytest.mark.asyncio
    async def test_swaymsg_fallback(self):
        wf = WindowFocus()
        m_wmctrl = AsyncMock(return_value=False)
        m_xdotool = AsyncMock(return_value=False)
        m_swaymsg = AsyncMock(return_value=True)
        m_ydotool = AsyncMock(return_value=False)
        with (
            patch.object(wf, "_try_wmctrl", m_wmctrl),
            patch.object(wf, "_try_xdotool", m_xdotool),
            patch.object(wf, "_try_swaymsg", m_swaymsg),
            patch.object(wf, "_try_ydotool", m_ydotool),
        ):
            result = await wf._focus_linux(_ref())
        assert result is True
        m_ydotool.assert_not_called()

    @pytest.mark.asyncio
    async def test_ydotool_fallback(self):
        wf = WindowFocus()
        m_wmctrl = AsyncMock(return_value=False)
        m_xdotool = AsyncMock(return_value=False)
        m_swaymsg = AsyncMock(return_value=False)
        m_ydotool = AsyncMock(return_value=True)
        with (
            patch.object(wf, "_try_wmctrl", m_wmctrl),
            patch.object(wf, "_try_xdotool", m_xdotool),
            patch.object(wf, "_try_swaymsg", m_swaymsg),
            patch.object(wf, "_try_ydotool", m_ydotool),
        ):
            result = await wf._focus_linux(_ref())
        assert result is True

    @pytest.mark.asyncio
    async def test_all_fail_returns_false(self):
        wf = WindowFocus()
        m_wmctrl = AsyncMock(return_value=False)
        m_xdotool = AsyncMock(return_value=False)
        m_swaymsg = AsyncMock(return_value=False)
        m_ydotool = AsyncMock(return_value=False)
        with (
            patch.object(wf, "_try_wmctrl", m_wmctrl),
            patch.object(wf, "_try_xdotool", m_xdotool),
            patch.object(wf, "_try_swaymsg", m_swaymsg),
            patch.object(wf, "_try_ydotool", m_ydotool),
        ):
            result = await wf._focus_linux(_ref())
        assert result is False


# ---------------------------------------------------------------------------
# _try_wmctrl
# ---------------------------------------------------------------------------


class TestTryWmctrl:
    @pytest.mark.asyncio
    async def test_success(self):
        wf = WindowFocus()
        proc = _fake_proc(returncode=0)
        with patch(
            "claude_monitor.window_focus.asyncio.create_subprocess_exec",
            return_value=proc,
        ):
            assert await wf._try_wmctrl(1234) is True

    @pytest.mark.asyncio
    async def test_nonzero_rc_returns_false(self):
        wf = WindowFocus()
        proc = _fake_proc(returncode=1, stderr=b"no window found")
        with patch(
            "claude_monitor.window_focus.asyncio.create_subprocess_exec",
            return_value=proc,
        ):
            assert await wf._try_wmctrl(1234) is False

    @pytest.mark.asyncio
    async def test_timeout_returns_false(self):
        wf = WindowFocus()
        proc = MagicMock()
        proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        with patch(
            "claude_monitor.window_focus.asyncio.create_subprocess_exec",
            return_value=proc,
        ):
            assert await wf._try_wmctrl(1234) is False

    @pytest.mark.asyncio
    async def test_not_installed_returns_false(self):
        wf = WindowFocus()
        with patch(
            "claude_monitor.window_focus.asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError(),
        ):
            assert await wf._try_wmctrl(1234) is False


# ---------------------------------------------------------------------------
# _try_xdotool
# ---------------------------------------------------------------------------


class TestTryXdotool:
    @pytest.mark.asyncio
    async def test_success(self):
        wf = WindowFocus()
        search_proc = _fake_proc(returncode=0, stdout=b"11111\n")
        activate_proc = _fake_proc(returncode=0)

        procs = iter([search_proc, activate_proc])
        with patch(
            "claude_monitor.window_focus.asyncio.create_subprocess_exec",
            side_effect=lambda *a, **kw: next(procs),
        ):
            assert await wf._try_xdotool(1234) is True

    @pytest.mark.asyncio
    async def test_no_windows_returns_false(self):
        wf = WindowFocus()
        search_proc = _fake_proc(returncode=0, stdout=b"")
        with patch(
            "claude_monitor.window_focus.asyncio.create_subprocess_exec",
            return_value=search_proc,
        ):
            assert await wf._try_xdotool(1234) is False

    @pytest.mark.asyncio
    async def test_activate_fails_returns_false(self):
        wf = WindowFocus()
        search_proc = _fake_proc(returncode=0, stdout=b"22222\n")
        activate_proc = _fake_proc(returncode=1, stderr=b"error")

        procs = iter([search_proc, activate_proc])
        with patch(
            "claude_monitor.window_focus.asyncio.create_subprocess_exec",
            side_effect=lambda *a, **kw: next(procs),
        ):
            assert await wf._try_xdotool(1234) is False

    @pytest.mark.asyncio
    async def test_not_installed_returns_false(self):
        wf = WindowFocus()
        with patch(
            "claude_monitor.window_focus.asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError(),
        ):
            assert await wf._try_xdotool(1234) is False


# ---------------------------------------------------------------------------
# _try_swaymsg
# ---------------------------------------------------------------------------


class TestTrySwaymsg:
    @pytest.mark.asyncio
    async def test_success(self):
        wf = WindowFocus()
        proc = _fake_proc(returncode=0)
        with patch(
            "claude_monitor.window_focus.asyncio.create_subprocess_exec",
            return_value=proc,
        ):
            assert await wf._try_swaymsg(1234) is True

    @pytest.mark.asyncio
    async def test_nonzero_rc_returns_false(self):
        wf = WindowFocus()
        proc = _fake_proc(returncode=1, stderr=b"no matching node")
        with patch(
            "claude_monitor.window_focus.asyncio.create_subprocess_exec",
            return_value=proc,
        ):
            assert await wf._try_swaymsg(1234) is False

    @pytest.mark.asyncio
    async def test_timeout_returns_false(self):
        wf = WindowFocus()
        proc = MagicMock()
        proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        with patch(
            "claude_monitor.window_focus.asyncio.create_subprocess_exec",
            return_value=proc,
        ):
            assert await wf._try_swaymsg(1234) is False

    @pytest.mark.asyncio
    async def test_not_installed_returns_false(self):
        wf = WindowFocus()
        with patch(
            "claude_monitor.window_focus.asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError(),
        ):
            assert await wf._try_swaymsg(1234) is False

    @pytest.mark.asyncio
    async def test_passes_pid_criterion(self):
        """swaymsg is invoked with [pid=<n>] focus."""
        wf = WindowFocus()
        proc = _fake_proc(returncode=0)
        captured = []

        async def capture(*args, **kwargs):
            captured.extend(args)
            return proc

        with patch(
            "claude_monitor.window_focus.asyncio.create_subprocess_exec",
            side_effect=capture,
        ):
            await wf._try_swaymsg(5678)

        assert "swaymsg" in captured
        assert "[pid=5678]" in captured
        assert "focus" in captured


# ---------------------------------------------------------------------------
# _try_ydotool
# ---------------------------------------------------------------------------


class TestTryYdotool:
    @pytest.mark.asyncio
    async def test_success(self):
        wf = WindowFocus()
        search_proc = _fake_proc(returncode=0, stdout=b"33333\n")
        activate_proc = _fake_proc(returncode=0)

        procs = iter([search_proc, activate_proc])
        with patch(
            "claude_monitor.window_focus.asyncio.create_subprocess_exec",
            side_effect=lambda *a, **kw: next(procs),
        ):
            assert await wf._try_ydotool(1234) is True

    @pytest.mark.asyncio
    async def test_no_windows_returns_false(self):
        wf = WindowFocus()
        search_proc = _fake_proc(returncode=0, stdout=b"")
        with patch(
            "claude_monitor.window_focus.asyncio.create_subprocess_exec",
            return_value=search_proc,
        ):
            assert await wf._try_ydotool(1234) is False

    @pytest.mark.asyncio
    async def test_activate_fails_returns_false(self):
        wf = WindowFocus()
        search_proc = _fake_proc(returncode=0, stdout=b"44444\n")
        activate_proc = _fake_proc(returncode=1, stderr=b"error")

        procs = iter([search_proc, activate_proc])
        with patch(
            "claude_monitor.window_focus.asyncio.create_subprocess_exec",
            side_effect=lambda *a, **kw: next(procs),
        ):
            assert await wf._try_ydotool(1234) is False

    @pytest.mark.asyncio
    async def test_timeout_returns_false(self):
        wf = WindowFocus()
        proc = MagicMock()
        proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        with patch(
            "claude_monitor.window_focus.asyncio.create_subprocess_exec",
            return_value=proc,
        ):
            assert await wf._try_ydotool(1234) is False

    @pytest.mark.asyncio
    async def test_not_installed_returns_false(self):
        wf = WindowFocus()
        with patch(
            "claude_monitor.window_focus.asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError(),
        ):
            assert await wf._try_ydotool(1234) is False
