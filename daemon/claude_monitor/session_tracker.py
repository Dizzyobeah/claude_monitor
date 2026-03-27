"""Track Claude Code session states from hook events."""

import os
import time
import dataclasses
from .protocol import EVENT_TO_STATE, NOTIFICATION_TO_STATE


@dataclasses.dataclass
class SessionInfo:
    session_id: str
    state: str = "IDLE"
    label: str = ""
    last_update: float = 0.0
    tty: str = ""
    ppid: str = ""

    def __post_init__(self):
        self.last_update = time.time()


class SessionTracker:
    def __init__(self, stale_timeout: int = 600):
        self.sessions: dict[str, SessionInfo] = {}
        self.stale_timeout = stale_timeout
        self._changed = False

    @property
    def changed(self) -> bool:
        """True if any session state changed since last clear."""
        val = self._changed
        self._changed = False
        return val

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
            if session_id in self.sessions:
                del self.sessions[session_id]
                self._changed = True
            return

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
        """Remove sessions that haven't been updated recently."""
        now = time.time()
        stale = [
            sid for sid, info in self.sessions.items()
            if now - info.last_update > self.stale_timeout
        ]
        for sid in stale:
            del self.sessions[sid]
        if stale:
            self._changed = True

    def get_ordered_sessions(self) -> list[SessionInfo]:
        """Return sessions ordered by priority (attention-needing first)."""
        attention_states = {"PERMISSION", "INPUT", "ERROR"}
        sessions = list(self.sessions.values())
        sessions.sort(key=lambda s: (
            0 if s.state in attention_states else 1,
            s.last_update,
        ))
        return sessions

    @staticmethod
    def _extract_label(cwd: str) -> str:
        """Extract a short label from the working directory."""
        if not cwd:
            return "unknown"
        return os.path.basename(cwd)[:20]
