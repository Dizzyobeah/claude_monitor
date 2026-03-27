"""Map Claude Code sessions to terminal windows/tabs."""

import logging
import dataclasses
from typing import Optional

import psutil

log = logging.getLogger(__name__)

# Known terminal applications on macOS
TERMINAL_APPS = {
    "iterm2": "iTerm2",
    "terminal": "Terminal",
    "warp": "Warp",
    "alacritty": "Alacritty",
    "kitty": "kitty",
    "wezterm-gui": "WezTerm",
    "ghostty": "Ghostty",
}


@dataclasses.dataclass
class WindowRef:
    app: str          # Terminal app identifier (e.g., "iterm2", "terminal")
    app_name: str     # Display name (e.g., "iTerm2", "Terminal")
    pid: int          # Terminal process PID


class TerminalMapper:
    """Find the terminal window for a Claude Code session."""

    def find_by_ppid(self, ppid: str) -> Optional[WindowRef]:
        """Walk up the process tree from the hook script PPID to find the terminal."""
        if not ppid:
            return None

        try:
            pid = int(ppid)
            proc = psutil.Process(pid)
        except (ValueError, psutil.NoSuchProcess):
            return None

        try:
            for ancestor in proc.parents():
                name = ancestor.name().lower()
                for key, display_name in TERMINAL_APPS.items():
                    if key in name:
                        return WindowRef(
                            app=key,
                            app_name=display_name,
                            pid=ancestor.pid,
                        )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        return None

    def find_by_tty(self, tty: str) -> Optional[WindowRef]:
        """Find terminal by matching TTY device."""
        if not tty or tty == "unknown":
            return None

        try:
            for proc in psutil.process_iter(["name", "pid", "terminal"]):
                try:
                    if proc.info["terminal"] == tty:
                        name = proc.info["name"].lower()
                        for key, display_name in TERMINAL_APPS.items():
                            if key in name:
                                return WindowRef(
                                    app=key,
                                    app_name=display_name,
                                    pid=proc.info["pid"],
                                )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass

        return None

    def find_terminal(self, ppid: str = "", tty: str = "") -> Optional[WindowRef]:
        """Try all strategies to find the terminal window."""
        ref = self.find_by_ppid(ppid)
        if ref:
            return ref
        return self.find_by_tty(tty)
