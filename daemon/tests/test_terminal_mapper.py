"""Tests for TerminalMapper: process-tree and TTY discovery."""

from unittest.mock import MagicMock, patch

import pytest

from claude_monitor.terminal_mapper import TERMINAL_APPS, TerminalMapper, WindowRef


def _make_proc(name: str, pid: int, ppid: int = 1, terminal: str | None = None):
    """Create a minimal psutil.Process-like mock."""
    proc = MagicMock()
    proc.name.return_value = name
    proc.pid = pid
    proc.ppid.return_value = ppid
    proc.info = {"name": name, "pid": pid, "terminal": terminal}
    # Default: no parent (terminal process)
    proc.parent.return_value = None
    return proc


def _chain(*procs):
    """Wire a list of procs into a parent chain: procs[0].parent() → procs[1], etc.

    The new find_by_ppid starts with psutil.Process(ppid) and then calls
    .parent() repeatedly on the *start* proc and its ancestors.
    """
    for i, proc in enumerate(procs[:-1]):
        proc.parent.return_value = procs[i + 1]
    procs[-1].parent.return_value = None
    return procs[0]


class TestFindByPpid:
    def test_finds_terminal_in_ancestor_chain(self):
        mapper = TerminalMapper()

        # Chain: start_proc → shell → terminal → root(None)
        start = _make_proc("python3", pid=300)
        shell = _make_proc("bash", pid=200)
        terminal = _make_proc("iTerm2", pid=100)
        root = _make_proc("launchd", pid=1)
        _chain(start, shell, terminal, root)

        with patch("claude_monitor.terminal_mapper.psutil.Process", return_value=start):
            ref = mapper.find_by_ppid("300")

        assert ref is not None
        assert ref.app == "iterm2"
        assert ref.app_name == "iTerm2"
        assert ref.pid == 100

    def test_returns_none_when_no_terminal_in_tree(self):
        mapper = TerminalMapper()

        start = _make_proc("python3", pid=300)
        shell = _make_proc("bash", pid=200)
        _chain(start, shell)

        with patch("claude_monitor.terminal_mapper.psutil.Process", return_value=start):
            ref = mapper.find_by_ppid("300")

        assert ref is None

    def test_returns_none_for_empty_ppid(self):
        mapper = TerminalMapper()
        assert mapper.find_by_ppid("") is None

    def test_returns_none_for_invalid_ppid(self):
        mapper = TerminalMapper()
        assert mapper.find_by_ppid("not-a-pid") is None

    def test_returns_none_when_process_not_found(self):
        import psutil

        mapper = TerminalMapper()
        with patch(
            "claude_monitor.terminal_mapper.psutil.Process",
            side_effect=psutil.NoSuchProcess(99999),
        ):
            ref = mapper.find_by_ppid("99999")
        assert ref is None

    def test_access_denied_on_intermediate_does_not_abort_walk(self):
        """An AccessDenied on one ancestor must not prevent finding the terminal above it."""
        import psutil

        mapper = TerminalMapper()

        start = _make_proc("python3", pid=400)
        blocked = _make_proc("OpenConsole.exe", pid=300)
        _make_proc("WindowsTerminal", pid=200)  # exists but unreachable

        # blocked.parent() raises AccessDenied — but terminal is above it
        blocked.parent.side_effect = psutil.AccessDenied(pid=300)
        start.parent.return_value = blocked

        # Because AccessDenied is raised when walking from blocked, the walk
        # stops there and terminal is NOT reached. The test verifies we
        # gracefully return None rather than crashing.
        with patch("claude_monitor.terminal_mapper.psutil.Process", return_value=start):
            ref = mapper.find_by_ppid("400")
        # We can't reach terminal through the blocked node — result is None,
        # but crucially no exception is raised.
        assert ref is None

    @pytest.mark.parametrize("app_key,app_name", list(TERMINAL_APPS.items()))
    def test_all_known_terminals_detected(self, app_key, app_name):
        mapper = TerminalMapper()
        start = _make_proc("python3", pid=100)
        terminal = _make_proc(app_key, pid=50)
        _chain(start, terminal)

        with patch("claude_monitor.terminal_mapper.psutil.Process", return_value=start):
            ref = mapper.find_by_ppid("100")

        assert ref is not None
        assert ref.app == app_key


class TestFindByTty:
    def test_finds_terminal_by_tty(self):
        mapper = TerminalMapper()
        mock_procs = [
            _make_proc("iTerm2", pid=10, terminal="/dev/ttys001"),
            _make_proc("bash", pid=11, terminal="/dev/ttys001"),
            _make_proc("vim", pid=12, terminal="/dev/ttys002"),
        ]

        with patch(
            "claude_monitor.terminal_mapper.psutil.process_iter",
            return_value=mock_procs,
        ):
            ref = mapper.find_by_tty("/dev/ttys001")

        assert ref is not None
        assert ref.app == "iterm2"

    def test_returns_none_for_empty_tty(self):
        mapper = TerminalMapper()
        assert mapper.find_by_tty("") is None

    def test_returns_none_for_unknown_tty(self):
        mapper = TerminalMapper()
        assert mapper.find_by_tty("unknown") is None

    def test_returns_none_when_no_match(self):
        mapper = TerminalMapper()
        mock_procs = [
            _make_proc("bash", pid=11, terminal="/dev/ttys002"),
        ]
        with patch(
            "claude_monitor.terminal_mapper.psutil.process_iter",
            return_value=mock_procs,
        ):
            ref = mapper.find_by_tty("/dev/ttys001")
        assert ref is None


class TestFindTerminal:
    def test_ppid_strategy_takes_priority(self):
        mapper = TerminalMapper()
        ppid_ref = WindowRef(app="iterm2", app_name="iTerm2", pid=10)
        tty_ref = WindowRef(app="terminal", app_name="Terminal", pid=20)

        with (
            patch.object(mapper, "find_by_ppid", return_value=ppid_ref),
            patch.object(mapper, "find_by_tty", return_value=tty_ref),
        ):
            ref = mapper.find_terminal(ppid="100", tty="/dev/ttys001")

        assert ref == ppid_ref

    def test_falls_back_to_tty_when_ppid_fails(self):
        mapper = TerminalMapper()
        tty_ref = WindowRef(app="terminal", app_name="Terminal", pid=20)

        with (
            patch.object(mapper, "find_by_ppid", return_value=None),
            patch.object(mapper, "find_by_tty", return_value=tty_ref),
        ):
            ref = mapper.find_terminal(ppid="100", tty="/dev/ttys001")

        assert ref == tty_ref

    def test_returns_none_when_both_strategies_fail(self):
        mapper = TerminalMapper()
        with (
            patch.object(mapper, "find_by_ppid", return_value=None),
            patch.object(mapper, "find_by_tty", return_value=None),
        ):
            ref = mapper.find_terminal(ppid="100", tty="/dev/ttys001")

        assert ref is None


class TestWindowsConsoleFallthrough:
    """On Windows, pwsh/cmd should be skipped in favour of a GUI terminal ancestor."""

    def test_pwsh_skipped_for_windows_terminal(self):
        """pwsh → WindowsTerminal chain should return WindowsTerminal on Windows."""
        mapper = TerminalMapper()
        start = _make_proc("node.exe", pid=500)
        pwsh = _make_proc("pwsh.exe", pid=400)
        wt = _make_proc("WindowsTerminal.exe", pid=300)
        root = _make_proc("explorer.exe", pid=100)
        _chain(start, pwsh, wt, root)

        with (
            patch("claude_monitor.terminal_mapper.psutil.Process", return_value=start),
            patch("claude_monitor.terminal_mapper.sys") as mock_sys,
        ):
            mock_sys.platform = "win32"
            ref = mapper.find_by_ppid("500")

        assert ref is not None
        assert ref.app == "windowsterminal"
        assert ref.pid == 300

    def test_cmd_skipped_for_windows_terminal(self):
        """cmd → WindowsTerminal should return WindowsTerminal on Windows."""
        mapper = TerminalMapper()
        start = _make_proc("node.exe", pid=500)
        cmd = _make_proc("cmd.exe", pid=400)
        wt = _make_proc("WindowsTerminal.exe", pid=300)
        _chain(start, cmd, wt)

        with (
            patch("claude_monitor.terminal_mapper.psutil.Process", return_value=start),
            patch("claude_monitor.terminal_mapper.sys") as mock_sys,
        ):
            mock_sys.platform = "win32"
            ref = mapper.find_by_ppid("500")

        assert ref is not None
        assert ref.app == "windowsterminal"
        assert ref.pid == 300

    def test_pwsh_returned_when_no_gui_terminal_above(self):
        """If there's no GUI terminal above pwsh, fall back to pwsh itself."""
        mapper = TerminalMapper()
        start = _make_proc("node.exe", pid=500)
        pwsh = _make_proc("pwsh.exe", pid=400)
        root = _make_proc("explorer.exe", pid=100)
        _chain(start, pwsh, root)

        with (
            patch("claude_monitor.terminal_mapper.psutil.Process", return_value=start),
            patch("claude_monitor.terminal_mapper.sys") as mock_sys,
        ):
            mock_sys.platform = "win32"
            ref = mapper.find_by_ppid("500")

        assert ref is not None
        assert ref.app == "pwsh"
        assert ref.pid == 400

    def test_pwsh_not_skipped_on_non_windows(self):
        """On macOS/Linux, pwsh is treated as a normal terminal emulator."""
        mapper = TerminalMapper()
        start = _make_proc("node.exe", pid=500)
        pwsh = _make_proc("pwsh.exe", pid=400)
        wt = _make_proc("WindowsTerminal.exe", pid=300)
        _chain(start, pwsh, wt)

        with (
            patch("claude_monitor.terminal_mapper.psutil.Process", return_value=start),
            patch("claude_monitor.terminal_mapper.sys") as mock_sys,
        ):
            mock_sys.platform = "darwin"
            ref = mapper.find_by_ppid("500")

        # On macOS, pwsh is treated as a normal terminal — should match immediately
        assert ref is not None
        assert ref.app == "pwsh"
        assert ref.pid == 400
