"""Map Claude Code / OpenCode sessions to terminal windows/tabs."""

import dataclasses
import logging
import sys

import psutil

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known terminal applications (macOS, Linux, Windows).
#
# Ordering matters: terminal emulators appear BEFORE editors so that when
# both appear in an ancestor chain (e.g. Windows Terminal → cmd → VS Code →
# integrated shell) the terminal emulator wins.  Within each tier, longer
# keys are checked first (the matching loop sorts by key length descending)
# to prevent short substrings like "terminal" from shadowing
# "gnome-terminal" or "windowsterminal".
# ---------------------------------------------------------------------------
TERMINAL_APPS = {
    # ---- macOS terminals ----
    "iterm2": "iTerm2",
    "terminal": "Terminal",
    "warp": "Warp",
    "alacritty": "Alacritty",
    "kitty": "kitty",
    "wezterm-gui": "WezTerm",
    "ghostty": "Ghostty",
    # ---- Linux terminals ----
    "gnome-terminal": "GNOME Terminal",
    "gnome-terminal-": "GNOME Terminal",
    "konsole": "Konsole",
    "xterm": "xterm",
    "xfce4-terminal": "Xfce Terminal",
    "tilix": "Tilix",
    "foot": "foot",
    "hyper": "Hyper",
    # ---- Windows terminals ----
    "windowsterminal": "Windows Terminal",
    "cmd": "cmd.exe",
    "pwsh": "PowerShell",
    "powershell": "PowerShell",
    # ---- Editors with integrated terminals ----
    # These are intentionally after the terminal emulators so a standalone
    # terminal always takes priority over an editor window.
    "code - insiders": "VS Code Insiders",
    "cursor": "Cursor",
    "windsurf": "Windsurf",
    "webstorm": "WebStorm",
    "idea": "IntelliJ IDEA",
    "code": "VS Code",  # kept last: "code" is a substring of "code - insiders"
}

# ---------------------------------------------------------------------------
# macOS: Electron-based apps (VS Code, Cursor …) appear in psutil as the
# generic process name "Electron".  We fall back to matching the exe path.
# ---------------------------------------------------------------------------
MACOS_EXE_FRAGMENTS: dict[str, tuple[str, str]] = {
    # Fragment to look for in proc.exe()  →  (app key, display name)
    "/iTerm.app": ("iterm2", "iTerm2"),
    "/Ghostty.app": ("ghostty", "Ghostty"),
    "/WezTerm.app": ("wezterm-gui", "WezTerm"),
    "/kitty.app": ("kitty", "kitty"),
    "/Alacritty.app": ("alacritty", "Alacritty"),
    "/Warp.app": ("warp", "Warp"),
    "/Visual Studio Code.app": ("code", "VS Code"),
    "/Visual Studio Code - Insiders.app": ("code - insiders", "VS Code Insiders"),
    "/Cursor.app": ("cursor", "Cursor"),
    "/Windsurf.app": ("windsurf", "Windsurf"),
}

# Fragments that indicate terminal emulators (as opposed to editors).
# When both a terminal and an editor are in the ancestor chain on macOS the
# terminal wins; we achieve this by scanning the chain once, recording the
# first terminal match and separately the first editor match, then returning
# the terminal match if any, otherwise the editor match.
# All terminal emulator keys (as opposed to editors with integrated terminals).
# Used to prefer a terminal over an editor when both appear in an ancestor chain.
_TERMINAL_EMULATOR_KEYS = frozenset(
    {
        # macOS
        "iterm2",
        "ghostty",
        "wezterm-gui",
        "kitty",
        "alacritty",
        "warp",
        "terminal",
        # Linux
        "gnome-terminal",
        "gnome-terminal-",
        "konsole",
        "xterm",
        "xfce4-terminal",
        "tilix",
        "foot",
        "hyper",
        # Windows
        "windowsterminal",
        "cmd",
        "pwsh",
        "powershell",
    }
)

# Windows console shells (cmd, pwsh, powershell) don't own visible HWNDs --
# the window belongs to a GUI host like Windows Terminal or conhost.  When we
# match one of these, we record it but keep walking ancestors to find the GUI
# terminal that actually owns the window.  Only used on Windows.
_WINDOWS_CONSOLE_SHELL_KEYS = frozenset({"cmd", "pwsh", "powershell"})


@dataclasses.dataclass
class WindowRef:
    app: str  # Terminal app identifier (e.g., "iterm2", "terminal")
    app_name: str  # Display name (e.g., "iTerm2", "Terminal")
    pid: int  # Terminal process PID


def _sorted_terminal_apps() -> list[tuple[str, str]]:
    """Return TERMINAL_APPS items sorted by key length descending.

    Longer keys are checked first so that e.g. "gnome-terminal" matches
    before the shorter substring "terminal".
    """
    return sorted(TERMINAL_APPS.items(), key=lambda kv: -len(kv[0]))


def _match_name(name: str) -> tuple[str, str] | None:
    """Return (key, display_name) if *name* contains a known terminal key, else None."""
    for key, display_name in _sorted_terminal_apps():
        if key in name:
            return key, display_name
    return None


class TerminalMapper:
    """Find the terminal window for a Claude Code / OpenCode session."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find_terminal(self, ppid: str = "", tty: str = "") -> WindowRef | None:
        """Try all strategies to find the terminal window.

        Strategy order:
          1. Walk the process ancestor chain from ppid (all platforms).
          2. Scan the process table for a process whose TTY matches (Unix only).
        """
        ref = self.find_by_ppid(ppid)
        if ref:
            return ref
        return self.find_by_tty(tty)

    # ------------------------------------------------------------------
    # Strategy 1 — ancestor chain walk
    # ------------------------------------------------------------------

    def find_by_ppid(self, ppid: str) -> WindowRef | None:
        """Walk up the process tree from *ppid* to find the terminal.

        Collects the full ancestor list first (catching AccessDenied
        per-process so a restricted intermediate process doesn't abort
        the entire walk), then matches against TERMINAL_APPS.
        """
        if not ppid:
            return None

        try:
            pid = int(ppid)
            start = psutil.Process(pid)
        except (ValueError, psutil.NoSuchProcess):
            return None

        # Build ancestor list manually so an AccessDenied on one node
        # doesn't discard everything above it.
        ancestors: list[psutil.Process] = []
        current = start
        while True:
            try:
                parent = current.parent()
                if parent is None:
                    break
                ancestors.append(parent)
                current = parent
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                # Can't go further up, but keep what we have so far.
                break

        # --- Name-based match (all platforms) ---
        # Prefer terminal emulators over editors: scan for the first entry
        # in ancestor order (child -> root) that matches any TERMINAL_APPS key.
        # Terminal keys come before editor keys in TERMINAL_APPS, but we also
        # do a two-pass scan: first looking only for terminal-emulator keys,
        # then for editor keys, so a terminal deeper in the chain wins over
        # an editor higher up.
        #
        # On Windows, console shells (cmd, pwsh, powershell) are technically
        # terminal emulator keys but they don't own visible HWNDs.  We treat
        # them like a fallback: record the match but keep walking ancestors
        # to find a GUI terminal (e.g. WindowsTerminal) that owns the window.
        terminal_ref: WindowRef | None = None
        shell_ref: WindowRef | None = None
        editor_ref: WindowRef | None = None

        for ancestor in ancestors:
            try:
                name = ancestor.name().lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

            match = _match_name(name)
            if match:
                key, display_name = match
                ref = WindowRef(app=key, app_name=display_name, pid=ancestor.pid)
                if key in _TERMINAL_EMULATOR_KEYS:
                    if sys.platform == "win32" and key in _WINDOWS_CONSOLE_SHELL_KEYS:
                        # Console shell — record but keep looking for a GUI terminal.
                        if shell_ref is None:
                            shell_ref = ref
                    else:
                        # GUI terminal emulator — stop immediately.
                        terminal_ref = ref
                        break
                elif editor_ref is None:
                    editor_ref = ref
                # Don't break on editor: keep scanning for a terminal emulator.

        if terminal_ref:
            return terminal_ref

        # --- macOS exe-path fallback (for Electron-based apps) ---
        if sys.platform == "darwin":
            exe_ref = self._find_by_exe_path_macos(ancestors)
            if exe_ref:
                return exe_ref

        # Fall back to console shell match (Windows), then editor match.
        return shell_ref or editor_ref

    # ------------------------------------------------------------------
    # Strategy 2 — TTY scan
    # ------------------------------------------------------------------

    def find_by_tty(self, tty: str) -> WindowRef | None:
        """Find terminal by matching TTY device (Unix only)."""
        if not tty or tty in ("unknown", "windows", ""):
            return None

        try:
            for proc in psutil.process_iter(["name", "pid", "terminal"]):
                try:
                    if proc.info["terminal"] == tty:
                        name = proc.info["name"].lower()
                        match = _match_name(name)
                        if match:
                            key, display_name = match
                            return WindowRef(
                                app=key,
                                app_name=display_name,
                                pid=proc.info["pid"],
                            )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as exc:
            log.debug("TTY scan failed: %s", exc)

        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_by_exe_path_macos(
        ancestors: list[psutil.Process],
    ) -> WindowRef | None:
        """On macOS, fall back to exe-path matching for Electron-based apps.

        VS Code, Cursor, etc. report their psutil process name as "Electron"
        rather than their app name, so the name-based scan misses them.
        We try to read proc.exe() and match against MACOS_EXE_FRAGMENTS.

        Same preference rule applies: terminal emulators beat editors.
        """
        terminal_ref: WindowRef | None = None
        editor_ref: WindowRef | None = None

        for ancestor in ancestors:
            try:
                exe = ancestor.exe()
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue

            for fragment, (key, display_name) in MACOS_EXE_FRAGMENTS.items():
                if fragment in exe:
                    ref = WindowRef(app=key, app_name=display_name, pid=ancestor.pid)
                    if key in _TERMINAL_EMULATOR_KEYS:
                        terminal_ref = ref
                        # Terminal found — no need to keep looking.
                        break
                    elif editor_ref is None:
                        editor_ref = ref
            if terminal_ref:
                break

        return terminal_ref or editor_ref
