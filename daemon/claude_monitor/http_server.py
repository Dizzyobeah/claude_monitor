"""HTTP server that receives Claude Code hook events."""

import json
import logging

from aiohttp import web

from .ble_manager import BleManager
from .ble_multi import BleMultiManager
from .session_tracker import SessionTracker

log = logging.getLogger(__name__)


def create_app(
    tracker: SessionTracker, ble: BleManager | BleMultiManager | None = None
) -> web.Application:
    """Create the aiohttp application for receiving hook POSTs."""
    # 2 MB max — large enough for OTA firmware uploads (~1.2 MB).
    # Hook payloads are tiny but /ota needs room for the full binary.
    app = web.Application(client_max_size=2 * 1024 * 1024)
    app["tracker"] = tracker
    app["ble"] = ble

    app.router.add_post("/hook", handle_hook)
    app.router.add_get("/status", handle_status)
    app.router.add_get("/metrics", handle_metrics)
    app.router.add_post("/ota", handle_ota)
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

    # Wake the sync loop immediately so state changes reach the display fast
    sync_wake = request.app.get("sync_wake")
    if sync_wake:
        sync_wake.set()

    return web.Response(text="ok")


async def handle_status(request: web.Request) -> web.Response:
    """Return current session states as JSON (for debugging).

    Sessions are returned sorted by display priority (attention-needing
    first, then most recently updated) with ``last_update`` included so
    callers can see when each session was last active.
    """
    tracker: SessionTracker = request.app["tracker"]
    ble: BleManager | BleMultiManager | None = request.app.get("ble")
    by_recency = sorted(
        tracker.sessions.values(),
        key=lambda s: s.last_update,
        reverse=True,
    )
    sessions = {
        info.session_id: {
            "state": info.state,
            "label": info.label,
            "last_update": info.last_update,
            "metrics": info.metrics,
        }
        for info in by_recency
    }
    return web.json_response(
        {
            "ble_connected": ble.connected if ble is not None else None,
            "sessions": sessions,
        }
    )


async def handle_ota(request: web.Request) -> web.Response:
    """Receive a firmware binary and push it to the ESP32 via BLE OTA."""
    ble: BleManager | BleMultiManager | None = request.app.get("ble")
    if not ble or not ble.connected:
        return web.Response(status=503, text="BLE not connected")

    firmware = await request.read()
    size = len(firmware)
    if size == 0:
        return web.Response(status=400, text="Empty firmware payload")

    log.info("OTA: received %d bytes, sending to ESP32...", size)

    # Step 1: Send ota_begin command with firmware size
    begin_msg = json.dumps({"cmd": "ota_begin", "size": size}) + "\n"
    await ble.send(begin_msg)

    # Step 2: Send firmware in chunks via BLE writes
    # BLE MTU is typically 247 bytes usable; use 200-byte chunks for safety
    chunk_size = 200
    sent = 0
    for i in range(0, size, chunk_size):
        chunk = firmware[i : i + chunk_size]
        await ble.send(chunk.decode("latin-1"))  # raw binary via BLE write
        sent += len(chunk)

    # Step 3: Send ota_end command to trigger validation + reboot
    end_msg = json.dumps({"cmd": "ota_end"}) + "\n"
    await ble.send(end_msg)

    log.info("OTA: sent %d bytes to ESP32, awaiting reboot", sent)
    return web.Response(text=f"OTA sent: {sent} bytes. ESP32 will reboot.")


async def handle_metrics(request: web.Request) -> web.Response:
    """Return per-session state duration metrics as JSON."""
    tracker: SessionTracker = request.app["tracker"]
    metrics = {
        sid: {"label": info.label, "state": info.state, "durations": info.metrics}
        for sid, info in tracker.sessions.items()
    }
    return web.json_response(metrics)


async def handle_health(request: web.Request) -> web.Response:
    """Health check endpoint."""
    return web.Response(text="ok")
