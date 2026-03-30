"""Focus terminal windows using platform-appropriate methods."""

import asyncio
import logging
import re
import sys
from typing import Any

from .terminal_mapper import WindowRef

log = logging.getLogger(__name__)

# Only allow safe characters in app names passed to osascript.
# Rejects quotes, backslashes, and control characters that could
# alter the meaning of the AppleScript string.
_SAFE_APP_NAME_RE = re.compile(r"^[A-Za-z0-9 _\-\.]+$")


class WindowFocus:
    """Activate terminal windows via the best available method for the platform."""

    async def trigger_dictation(self) -> bool:
        """Trigger system dictation.

        macOS:   Simulates Globe/fn key double-press (requires Accessibility
                 permission in System Settings > Privacy & Security).
        Windows: Simulates Win+H to open Voice Typing (Windows 10 2004+).
        Linux:   Not yet supported.
        """
        if sys.platform == "darwin":
            return await self._trigger_dictation_macos()
        elif sys.platform == "win32":
            return await self._trigger_dictation_windows()
        else:
            log.warning("Dictation trigger not yet supported on Linux")
            return False

    async def _trigger_dictation_macos(self) -> bool:
        """Trigger macOS dictation by simulating the Globe/fn key double-press."""
        # key code 63 = fn/Globe key on macOS
        script = (
            'tell application "System Events"\n'
            "    key code 63\n"
            "    delay 0.05\n"
            "    key code 63\n"
            "end tell"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript",
                "-e",
                script,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            if proc.returncode != 0:
                log.warning("Dictation trigger failed: %s", stderr.decode().strip())
                return False
            log.info("Dictation triggered via fn-fn")
            return True
        except asyncio.TimeoutError:
            log.warning("Dictation trigger timed out")
            return False
        except FileNotFoundError:
            log.error("osascript not found")
            return False

    async def _trigger_dictation_windows(self) -> bool:
        """Trigger Windows Voice Typing by simulating Win+H.

        Uses the SendInput Win32 API via ctypes.  Requires Windows 10
        version 2004 or later.
        """
        try:
            result = await asyncio.get_running_loop().run_in_executor(
                None,
                self._send_win_h,
            )
            if result:
                log.info("Dictation triggered via Win+H")
            else:
                log.warning("Win+H SendInput returned 0 — dictation may not have triggered")
            return result
        except Exception as exc:
            log.error("Windows dictation error: %s", exc)
            return False

    @staticmethod
    def _send_win_h() -> bool:
        """Send Win+H keystroke via SendInput to trigger Voice Typing."""
        import ctypes
        import ctypes.wintypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]

        VK_LWIN = 0x5B
        VK_H = 0x48
        KEYEVENTF_KEYUP = 0x0002

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", ctypes.wintypes.WORD),
                ("wScan", ctypes.wintypes.WORD),
                ("dwFlags", ctypes.wintypes.DWORD),
                ("time", ctypes.wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class INPUT(ctypes.Structure):
            class _INPUT_UNION(ctypes.Union):
                _fields_ = [("ki", KEYBDINPUT)]

            _fields_ = [
                ("type", ctypes.wintypes.DWORD),
                ("_input", _INPUT_UNION),
            ]

        def _kbd(vk: int, flags: int = 0) -> INPUT:
            inp = INPUT()
            inp.type = 1  # INPUT_KEYBOARD
            inp._input.ki.wVk = vk
            inp._input.ki.dwFlags = flags
            return inp

        # Win down, H down, H up, Win up
        inputs = (INPUT * 4)(
            _kbd(VK_LWIN),
            _kbd(VK_H),
            _kbd(VK_H, KEYEVENTF_KEYUP),
            _kbd(VK_LWIN, KEYEVENTF_KEYUP),
        )
        sent = user32.SendInput(4, ctypes.byref(inputs), ctypes.sizeof(INPUT))
        return sent == 4

    async def focus(self, ref: WindowRef) -> bool:
        """Bring the terminal window to the front. Returns True on success."""
        if sys.platform == "darwin":
            return await self._focus_macos(ref)
        elif sys.platform == "win32":
            return await self._focus_windows(ref)
        else:
            return await self._focus_linux(ref)

    # ------------------------------------------------------------------ macOS

    async def _focus_macos(self, ref: WindowRef) -> bool:
        """Focus using AppleScript/osascript."""
        script = self._build_applescript(ref)
        if not script:
            return False

        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript",
                "-e",
                script,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            if proc.returncode != 0:
                log.warning("osascript failed: %s", stderr.decode().strip())
                return False
            log.info("Focused %s (pid %d)", ref.app_name, ref.pid)
            return True
        except asyncio.TimeoutError:
            log.warning("osascript timed out for %s", ref.app_name)
            return False
        except FileNotFoundError:
            log.error("osascript not found — macOS only")
            return False

    def _build_applescript(self, ref: WindowRef) -> str:
        """Build the AppleScript to focus the terminal.

        App names are validated against a safe character set to prevent
        AppleScript injection via crafted process names.
        """
        if not _SAFE_APP_NAME_RE.match(ref.app_name):
            log.warning("Rejected unsafe app name for AppleScript: %r", ref.app_name)
            return ""
        if ref.app == "iterm2":
            return 'tell application "iTerm2"\n    activate\nend tell'
        elif ref.app == "terminal":
            return (
                'tell application "Terminal"\n'
                "    activate\n"
                "    set index of front window to 1\n"
                "end tell"
            )
        elif ref.app in ("warp", "alacritty", "kitty", "wezterm-gui", "ghostty"):
            return f'tell application "{ref.app_name}"\n    activate\nend tell'
        else:
            # Fallback: activate by PID via System Events
            return (
                'tell application "System Events"\n'
                f"    set frontmost of (first process whose unix id is {ref.pid}) to true\n"
                "end tell"
            )

    # ----------------------------------------------------------------- Windows

    async def _focus_windows(self, ref: WindowRef) -> bool:
        """Focus using Win32 API via ctypes (no extra dependencies).

        Windows 2000+ introduced a foreground lock that prevents background
        processes from stealing focus via SetForegroundWindow alone — the call
        silently fails and only flashes the taskbar.  The standard workaround
        (used by AutoHotkey and similar tools) is to temporarily attach the
        calling thread's input queue to the target window's thread with
        AttachThreadInput, which tricks the OS into granting foreground
        permission.  We unlink immediately after.
        """
        try:
            loop = asyncio.get_running_loop()

            # Find the main window HWND for the given PID
            hwnd = await loop.run_in_executor(None, self._find_hwnd_for_pid, ref.pid)

            # Defensive fallback: if the PID has no visible HWND (e.g. pwsh.exe
            # inside Windows Terminal), walk ancestor PIDs until we find one
            # that does.  This handles cases where terminal_mapper returned a
            # shell PID instead of the GUI terminal PID.
            if not hwnd:
                hwnd = await loop.run_in_executor(None, self._find_hwnd_by_ancestor_walk, ref.pid)

            if not hwnd:
                log.warning("Could not find window for pid %d on Windows", ref.pid)
                return False

            result = await loop.run_in_executor(None, self._set_foreground_attached, hwnd, ref.pid)
            if result:
                log.info("Focused %s (pid %d)", ref.app_name, ref.pid)
            else:
                log.warning("Focus failed for %s (pid %d)", ref.app_name, ref.pid)
            return result
        except Exception as exc:
            log.error("Windows focus error: %s", exc)
            return False

    @staticmethod
    def _set_foreground_attached(hwnd: int, pid: int) -> bool:
        """Bring hwnd to the foreground using the AttachThreadInput trick.

        By briefly attaching our thread's input state to the foreground
        window's thread, Windows grants us permission to call
        SetForegroundWindow successfully even when we don't own the
        foreground.  We immediately detach to avoid side-effects.
        """
        import ctypes
        import ctypes.wintypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

        # SW_RESTORE = 9: restore if minimised
        user32.ShowWindow(hwnd, 9)

        # Get the thread of the window we want to focus
        # Get the thread ID of the window we want to focus
        target_tid_val = user32.GetWindowThreadProcessId(hwnd, None)

        # Get the thread of the current foreground window
        fg_hwnd = user32.GetForegroundWindow()
        fg_tid_val = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0

        our_tid_val = kernel32.GetCurrentThreadId()

        attached_to_fg = False
        attached_to_target = False

        try:
            # Attach our thread to the foreground window's thread so that
            # SetForegroundWindow thinks we already own the foreground.
            if fg_tid_val and fg_tid_val != our_tid_val:  # noqa: SIM102
                if user32.AttachThreadInput(our_tid_val, fg_tid_val, True):
                    attached_to_fg = True

            # Also attach to the target thread (some compositors require this)
            if (  # noqa: SIM102
                target_tid_val and target_tid_val != our_tid_val and target_tid_val != fg_tid_val
            ):
                if user32.AttachThreadInput(our_tid_val, target_tid_val, True):
                    attached_to_target = True

            user32.BringWindowToTop(hwnd)
            result = bool(user32.SetForegroundWindow(hwnd))
            return result
        finally:
            # Always detach — leaving threads attached causes input routing bugs
            if attached_to_fg:
                user32.AttachThreadInput(our_tid_val, fg_tid_val, False)
            if attached_to_target:
                user32.AttachThreadInput(our_tid_val, target_tid_val, False)

    @staticmethod
    def _find_hwnd_for_pid(pid: int) -> int | None:
        """Enumerate top-level windows and return the first visible one owned by pid."""
        import ctypes
        import ctypes.wintypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        found: Any = ctypes.wintypes.HWND(0)

        EnumWindowsProc = ctypes.WINFUNCTYPE(  # type: ignore[attr-defined]
            ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
        )

        def callback(hwnd: int, _lparam: int) -> bool:
            nonlocal found
            if not user32.IsWindowVisible(hwnd):
                return True
            lpdw_pid = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(lpdw_pid))
            if lpdw_pid.value == pid:
                found = hwnd
                return False  # Stop enumeration
            return True

        user32.EnumWindows(EnumWindowsProc(callback), 0)
        return found or None

    @staticmethod
    def _find_hwnd_by_ancestor_walk(pid: int) -> int | None:
        """Walk parent PIDs to find the first ancestor with a visible HWND.

        On Windows, console shells (pwsh.exe, cmd.exe) don't own visible
        windows — the HWND belongs to a GUI host like Windows Terminal.
        This method walks up the process tree and returns the first visible
        HWND it finds.
        """
        import psutil

        try:
            proc = psutil.Process(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

        for _ in range(15):  # safety cap
            try:
                proc = proc.parent()
                if proc is None:
                    break
                hwnd = WindowFocus._find_hwnd_for_pid(proc.pid)
                if hwnd:
                    log.debug(
                        "Ancestor HWND walk: found hwnd for pid %d (%s)",
                        proc.pid,
                        proc.name(),
                    )
                    return hwnd
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break
        return None

    # ------------------------------------------------------------------ Linux

    async def _focus_linux(self, ref: WindowRef) -> bool:
        """Focus using the best available tool for the current Linux session.

        Try order (X11 first, then Wayland):
          1. wmctrl   — X11/XWayland, matches by PID
          2. xdotool  — X11/XWayland, matches by PID
          3. swaymsg  — native Wayland (Sway / wlroots compositors)
          4. ydotool  — native Wayland (uinput-based, needs ydotoold running)
        """
        if await self._try_wmctrl(ref.pid):
            return True
        if await self._try_xdotool(ref.pid):
            return True
        if await self._try_swaymsg(ref.pid):
            return True
        if await self._try_ydotool(ref.pid):
            return True
        log.warning(
            "Could not focus terminal on Linux — "
            "install wmctrl or xdotool (X11) or swaymsg/ydotool (Wayland)"
        )
        return False

    async def _try_wmctrl(self, pid: int) -> bool:
        """Attempt to focus via wmctrl -ip <pid>."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "wmctrl",
                "-ip",
                str(pid),
                "-a",
                ".",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            if proc.returncode == 0:
                log.info("Focused pid %d via wmctrl", pid)
                return True
            log.debug("wmctrl failed (rc %d): %s", proc.returncode, stderr.decode().strip())
            return False
        except asyncio.TimeoutError:
            log.warning("wmctrl timed out for pid %d", pid)
            return False
        except FileNotFoundError:
            log.debug("wmctrl not found")
            return False

    async def _try_xdotool(self, pid: int) -> bool:
        """Attempt to focus via xdotool search --pid / windowactivate."""
        try:
            # First find the window ID(s) for this PID
            search = await asyncio.create_subprocess_exec(
                "xdotool",
                "search",
                "--pid",
                str(pid),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(search.communicate(), timeout=5.0)
            wids = stdout.decode().split()
            if not wids:
                log.debug("xdotool found no windows for pid %d", pid)
                return False

            # Activate the first window found
            activate = await asyncio.create_subprocess_exec(
                "xdotool",
                "windowactivate",
                "--sync",
                wids[0],
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(activate.communicate(), timeout=5.0)
            if activate.returncode == 0:
                log.info("Focused pid %d (wid %s) via xdotool", pid, wids[0])
                return True
            log.debug("xdotool windowactivate failed: %s", stderr.decode().strip())
            return False
        except asyncio.TimeoutError:
            log.warning("xdotool timed out for pid %d", pid)
            return False
        except FileNotFoundError:
            log.debug("xdotool not found")
            return False

    async def _try_swaymsg(self, pid: int) -> bool:
        """Attempt to focus via swaymsg (Sway / wlroots Wayland compositors)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "swaymsg",
                f"[pid={pid}]",
                "focus",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            if proc.returncode == 0:
                log.info("Focused pid %d via swaymsg", pid)
                return True
            log.debug("swaymsg failed (rc %d): %s", proc.returncode, stderr.decode().strip())
            return False
        except asyncio.TimeoutError:
            log.warning("swaymsg timed out for pid %d", pid)
            return False
        except FileNotFoundError:
            log.debug("swaymsg not found")
            return False

    async def _try_ydotool(self, pid: int) -> bool:
        """Attempt to focus via ydotool (Wayland, requires ydotoold daemon)."""
        try:
            search = await asyncio.create_subprocess_exec(
                "ydotool",
                "search",
                "--pid",
                str(pid),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(search.communicate(), timeout=5.0)
            wids = stdout.decode().split()
            if not wids:
                log.debug("ydotool found no windows for pid %d", pid)
                return False

            activate = await asyncio.create_subprocess_exec(
                "ydotool",
                "windowactivate",
                "--sync",
                wids[0],
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(activate.communicate(), timeout=5.0)
            if activate.returncode == 0:
                log.info("Focused pid %d (wid %s) via ydotool", pid, wids[0])
                return True
            log.debug("ydotool windowactivate failed: %s", stderr.decode().strip())
            return False
        except asyncio.TimeoutError:
            log.warning("ydotool timed out for pid %d", pid)
            return False
        except FileNotFoundError:
            log.debug("ydotool not found")
            return False
