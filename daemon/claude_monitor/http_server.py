"""HTTP server that receives Claude Code hook events."""

import logging
from aiohttp import web
from .session_tracker import SessionTracker
from .ble_manager import BleManager

log = logging.getLogger(__name__)


def create_app(
    tracker: SessionTracker, ble: BleManager | None = None
) -> web.Application:
    """Create the aiohttp application for receiving hook POSTs."""
    app = web.Application()
    app["tracker"] = tracker
    app["ble"] = ble

    app.router.add_post("/hook", handle_hook)
    app.router.add_get("/status", handle_status)
    app.router.add_get("/health", handle_health)

    return app


async def handle_hook(request: web.Request) -> web.Response:
    """Handle a hook event POST from Claude Code."""
    tracker: SessionTracker = request.app["tracker"]

    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="Invalid JSON")

    event = data.get("hook_event_name", "")
    session_id = data.get("session_id", "")

    if not event or not session_id:
        return web.Response(status=400, text="Missing hook_event_name or session_id")

    # Extract terminal metadata from headers
    tty = request.headers.get("X-TTY", "")
    ppid = request.headers.get("X-PPID", "")

    log.debug("Hook event: %s for session %s", event, session_id[:8])
    tracker.update_session(session_id, event, data, tty=tty, ppid=ppid)

    return web.Response(text="ok")


async def handle_status(request: web.Request) -> web.Response:
    """Return current session states as JSON (for debugging)."""
    tracker: SessionTracker = request.app["tracker"]
    ble: BleManager | None = request.app.get("ble")
    sessions = {
        sid: {"state": info.state, "label": info.label}
        for sid, info in tracker.sessions.items()
    }
    return web.json_response(
        {
            "ble_connected": ble.connected if ble is not None else None,
            "sessions": sessions,
        }
    )


async def handle_health(request: web.Request) -> web.Response:
    """Health check endpoint."""
    return web.Response(text="ok")
