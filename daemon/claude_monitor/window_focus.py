"""Focus terminal windows on macOS using AppleScript/osascript."""

import asyncio
import logging
from .terminal_mapper import WindowRef

log = logging.getLogger(__name__)


class WindowFocus:
    """Activate terminal windows via osascript."""

    async def focus(self, ref: WindowRef) -> bool:
        """Bring the terminal window to the front. Returns True on success."""
        script = self._build_script(ref)
        if not script:
            return False

        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e", script,
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
            log.error("osascript not found - macOS only")
            return False

    def _build_script(self, ref: WindowRef) -> str:
        """Build the AppleScript to focus the terminal."""
        if ref.app == "iterm2":
            return (
                'tell application "iTerm2"\n'
                "    activate\n"
                "end tell"
            )
        elif ref.app == "terminal":
            return (
                'tell application "Terminal"\n'
                "    activate\n"
                "    set index of front window to 1\n"
                "end tell"
            )
        elif ref.app in ("warp", "alacritty", "kitty", "wezterm-gui", "ghostty"):
            # Generic: activate by app name
            return (
                f'tell application "{ref.app_name}"\n'
                f"    activate\n"
                f"end tell"
            )
        else:
            # Fallback: activate by PID via System Events
            return (
                'tell application "System Events"\n'
                f"    set frontmost of (first process whose unix id is {ref.pid}) to true\n"
                "end tell"
            )
