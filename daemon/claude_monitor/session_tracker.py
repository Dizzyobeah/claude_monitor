"""Track Claude Code session states from hook events."""

import os
import time
import dataclasses
from .protocol import EVENT_TO_STATE, NOTIFICATION_TO_STATE

# How long to keep a session visible after SessionEnd before removing it.
# This prevents a "No active sessions" flash when OpenCode briefly deletes
# and recreates a session (e.g. on session switch or /undo), and gives the
# display a graceful fade-out when a session truly ends.
SESSION_REMOVAL_GRACE_S = 5.0


@dataclasses.dataclass
class SessionInfo:
    session_id: str
    state: str = "IDLE"
    label: str = ""
    last_update: float = dataclasses.field(default_factory=time.time)
    tty: str = ""
    ppid: str = ""


class SessionTracker:
    def __init__(self, stale_timeout: int = 600):
        self.sessions: dict[str, SessionInfo] = {}
        self.stale_timeout = stale_timeout
        self._changed = False
        self._removed_ids: list[str] = []
        # Sessions pending removal: {session_id: scheduled_removal_time}
        self._pending_removal: dict[str, float] = {}
        # Flips True the first time any session is created; never resets.
        self.ever_had_session: bool = False

    @property
    def is_idle(self) -> bool:
        """True when all sessions have ended and nothing is pending removal.

        Only returns True after at least one session has been seen, so the
        daemon doesn't exit on cold start before any hook fires.
        """
        return self.ever_had_session and not self.sessions and not self._pending_removal

    @property
    def changed(self) -> bool:
        """True if any session state changed since last clear."""
        val = self._changed
        self._changed = False
        return val

    def pop_removed_ids(self) -> list[str]:
        """Return and clear the list of session IDs removed since last call."""
        ids = self._removed_ids
        self._removed_ids = []
        return ids

    def _remove_session(self, session_id: str) -> None:
        """Internal: delete a session and record it for BLE removal."""
        if session_id in self.sessions:
            del self.sessions[session_id]
            self._removed_ids.append(session_id)
            self._changed = True
        self._pending_removal.pop(session_id, None)

    def update_session(
        self,
        session_id: str,
        event: str,
        data: dict,
        tty: str = "",
        ppid: str = "",
    ) -> None:
        """Process a hook event and update session state."""
        if event == "SessionEnd":
            # Don't remove immediately — show INPUT state for a grace period so
            # a brief delete+recreate (session switch, /undo) never flashes
            # "No active sessions" on the display.
            if session_id in self.sessions:
                info = self.sessions[session_id]
                if info.state != "INPUT":
                    info.state = "INPUT"
                    self._changed = True
                info.last_update = time.time()
                self._pending_removal[session_id] = (
                    time.time() + SESSION_REMOVAL_GRACE_S
                )
            return

        # Cancel any pending removal if the session is back
        self._pending_removal.pop(session_id, None)

        # Determine new state
        state: str | None = None
        if event == "Notification":
            ntype = data.get("notification_type", "")
            state = NOTIFICATION_TO_STATE.get(ntype)
        else:
            state = EVENT_TO_STATE.get(event)

        if state is None:
            return  # Unrecognized event

        info = self.sessions.get(session_id)
        if info is None:
            info = SessionInfo(session_id=session_id)
            self.sessions[session_id] = info
            self._changed = True  # New session always marks as changed
            self.ever_had_session = True

        if info.state != state:
            self._changed = True

        info.state = state
        info.label = self._extract_label(data.get("cwd", ""))
        info.last_update = time.time()

        if tty and not info.tty:
            info.tty = tty
        if ppid and not info.ppid:
            info.ppid = ppid

    def prune_stale(self) -> None:
        """Remove sessions that haven't been updated recently, and process
        any sessions whose removal grace period has elapsed."""
        now = time.time()

        # Process deferred removals
        due = [sid for sid, t in self._pending_removal.items() if now >= t]
        for sid in due:
            self._remove_session(sid)

        # Remove sessions with no updates beyond the stale timeout
        stale = [
            sid
            for sid, info in self.sessions.items()
            if now - info.last_update > self.stale_timeout
            and sid not in self._pending_removal  # already being handled
        ]
        for sid in stale:
            self._remove_session(sid)

    def get_ordered_sessions(self) -> list[SessionInfo]:
        """Return sessions ordered by priority (attention-needing first)."""
        attention_states = {"PERMISSION", "INPUT", "ERROR"}
        sessions = list(self.sessions.values())
        sessions.sort(
            key=lambda s: (
                0 if s.state in attention_states else 1,
                -s.last_update,  # Most recently updated first within each tier
            )
        )
        return sessions

    @staticmethod
    def _extract_label(cwd: str) -> str:
        """Extract a short label from the working directory."""
        if not cwd:
            return "unknown"
        return os.path.basename(cwd)[:20]
