"""Serial protocol constants shared with ESP32 firmware."""

import json

# Session states (must match firmware SessionState enum)
STATES = {"IDLE", "THINKING", "TOOL_USE", "PERMISSION", "INPUT", "ERROR"}

# Hook event to state mapping
EVENT_TO_STATE: dict[str, str | None] = {
    "SessionStart": "IDLE",
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


def make_state_msg(sid: str, state: str, label: str, idx: int, total: int) -> str:
    """Build a state update JSON line for the ESP32."""
    return json.dumps({
        "cmd": "state",
        "sid": sid[:5],
        "state": state,
        "label": label[:20],
        "idx": idx,
        "total": total,
    }) + "\n"


def make_remove_msg(sid: str) -> str:
    """Build a session removal JSON line for the ESP32."""
    return json.dumps({"cmd": "remove", "sid": sid[:5]}) + "\n"


def make_ping_msg() -> str:
    return '{"cmd":"ping"}\n'
