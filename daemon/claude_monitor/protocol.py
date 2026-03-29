"""Serial protocol constants shared with ESP32 firmware."""

import hashlib
import json

# Session states (must match firmware SessionState enum)
STATES = {"IDLE", "THINKING", "TOOL_USE", "PERMISSION", "INPUT", "ERROR"}

# Hook event to state mapping
EVENT_TO_STATE: dict[str, str | None] = {
    "SessionStart": "INPUT",
    "UserPromptSubmit": "THINKING",
    "PreToolUse": "TOOL_USE",
    "PostToolUse": "THINKING",
    "PostToolUseFailure": "ERROR",
    "PermissionRequest": "PERMISSION",
    "Stop": "INPUT",
    "StopFailure": "ERROR",
    "SubagentStart": "THINKING",
    "SubagentStop": "THINKING",
    "SessionEnd": None,  # Signals removal
}

# Notification subtypes override
NOTIFICATION_TO_STATE: dict[str, str] = {
    "permission_prompt": "PERMISSION",
    "idle_prompt": "INPUT",
}


def short_sid(session_id: str) -> str:
    """Return a stable 5-char hex SID derived from the full session ID.

    Using a hash avoids collisions when session IDs share a common prefix
    (e.g. OpenCode's 'ses_2...' sessions all truncate to the same 5 chars).
    The result is lowercase hex so it is safe in JSON and fits the firmware's
    6-byte sid buffer (5 chars + null terminator).
    """
    return hashlib.sha1(session_id.encode()).hexdigest()[:5]  # noqa: S324 — not for security


def make_state_msg(sid: str, state: str, label: str, idx: int, total: int) -> str:
    """Build a state update JSON line for the ESP32."""
    return (
        json.dumps(
            {
                "cmd": "state",
                "sid": short_sid(sid),
                "state": state,
                "label": label[:20],
                "idx": idx,
                "total": total,
            }
        )
        + "\n"
    )


def make_remove_msg(sid: str) -> str:
    """Build a session removal JSON line for the ESP32."""
    return json.dumps({"cmd": "remove", "sid": short_sid(sid)}) + "\n"


def make_ping_msg() -> str:
    return '{"cmd":"ping"}\n'
