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
    ordered = tracker.get_ordered_sessions()
    sessions = {
        info.session_id: {
            "state": info.state,
            "label": info.label,
            "last_update": info.last_update,
        }
        for info in ordered
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

    # Pause the sync-loop watchdog during OTA — the BLE writes block the event loop.
    daemon = request.app.get("daemon")
    if daemon:
        daemon._ota_in_progress = True

    # Step 1: Send ota_begin and wait for ACK
    ble.prepare_ota_ack()
    begin_msg = json.dumps({"cmd": "ota_begin", "size": size}) + "\n"
    await ble.send(begin_msg)
    if not await ble.wait_for_ota_ack(timeout=10):
        return web.Response(status=500, text="ESP32 failed to start OTA")

    # Step 2: Send firmware in raw binary chunks.
    # Send BATCH_SIZE chunks before waiting for an ACK to reduce round-trip
    # overhead.  The ESP32 processes each chunk immediately in _onWrite() and
    # sets an ACK flag that update() drains — we only need the ACK to confirm
    # the batch was received, not every individual chunk.
    chunk_size = 512
    batch_size = 16  # ACK every 16 chunks (8 KB)
    sent = 0
    chunks_since_ack = 0
    for i in range(0, size, chunk_size):
        chunk = firmware[i : i + chunk_size]
        await ble.send_bytes(chunk)
        sent += len(chunk)
        chunks_since_ack += 1
        if chunks_since_ack >= batch_size or sent >= size:
            if not await ble.wait_for_ota_ack(timeout=30):
                if daemon:
                    daemon._ota_in_progress = False
                return web.Response(status=500, text=f"OTA ACK failed at {sent} bytes")
            chunks_since_ack = 0
        if sent % 32768 < chunk_size:
            log.info("OTA: %d / %d bytes (%.0f%%)", sent, size, 100 * sent / size)

    # Step 3: Send ota_end to trigger validation + reboot
    end_msg = json.dumps({"cmd": "ota_end"}) + "\n"
    await ble.send(end_msg)

    if daemon:
        daemon._ota_in_progress = False

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
