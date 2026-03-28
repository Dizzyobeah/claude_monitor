"""BLE client that auto-discovers and connects to the Claude Monitor ESP32 display."""

import asyncio
import json
import logging
from typing import Callable, Coroutine, Any

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

log = logging.getLogger(__name__)

# Must match the UUIDs in ble_protocol.h
SERVICE_UUID = "c0de0000-cafe-babe-c0de-000000000001"
CHAR_RX_UUID = "c0de0001-cafe-babe-c0de-000000000001"  # We write commands here
CHAR_TX_UUID = "c0de0002-cafe-babe-c0de-000000000001"  # We receive notifications here

RECONNECT_DELAY = 3.0  # Seconds between reconnection attempts
CONNECT_TIMEOUT = 20.0  # Seconds to wait for a connection
SCAN_TIMEOUT = 10.0  # Seconds per scan attempt


class BleManager:
    def __init__(self):
        self._client: BleakClient | None = None
        self._connected = False
        self._on_message: Callable[[dict], Coroutine[Any, Any, None]] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        # Signals the _connect coroutine to abort when a send error is detected
        self._force_disconnect: asyncio.Event | None = None

    @property
    def connected(self) -> bool:
        return self._connected

    async def run(
        self, on_message: Callable[[dict], Coroutine[Any, Any, None]]
    ) -> None:
        """Main loop: scan for display, connect, handle notifications, reconnect."""
        self._on_message = on_message
        self._loop = asyncio.get_running_loop()

        while True:
            try:
                device = await self._scan()
                if not device:
                    log.info(
                        "No Claude Monitor display found — retrying in %.0fs...",
                        RECONNECT_DELAY,
                    )
                    await asyncio.sleep(RECONNECT_DELAY)
                    continue

                await self._connect(device)

            except Exception as e:
                log.warning(
                    "BLE error: %s (%s) — reconnecting in %.0fs...",
                    e or "(no message)",
                    type(e).__name__,
                    RECONNECT_DELAY,
                )

            # Always clean up state before retrying
            self._connected = False
            self._client = None
            self._force_disconnect = None
            await asyncio.sleep(RECONNECT_DELAY)

    async def send(self, data: str) -> None:
        """Send a JSON message to the ESP32 display via BLE write."""
        if not self._connected or not self._client:
            return
        try:
            payload = data.rstrip("\n").encode("utf-8")
            log.debug("BLE send (%d bytes): %s", len(payload), payload[:120])
            # response=True (Write With Response) is more reliable on Windows —
            # Write Without Response packets can be silently dropped by the WinRT
            # BLE stack when the TX queue is full or the connection has just formed.
            await self._client.write_gatt_char(CHAR_RX_UUID, payload, response=True)
            log.debug("BLE send OK")
        except Exception as e:
            log.warning("BLE send error: %s — triggering reconnect", e)
            self._connected = False
            # Wake the _connect coroutine so it exits and the run() loop retries
            if self._force_disconnect:
                self._force_disconnect.set()

    async def _scan(self) -> BLEDevice | None:
        """Scan using a continuous scanner and return the BLEDevice the moment
        it's detected.  Keeping the scanner running while we hand the device
        to BleakClient avoids the Windows WinRT cache miss that causes
        BleakDeviceNotFoundError or silent connection hangs.
        """
        log.info("Scanning for Claude Monitor BLE display...")

        found_event: asyncio.Event = asyncio.Event()
        found_device: BLEDevice | None = None

        def detection_callback(device: BLEDevice, adv: AdvertisementData) -> None:
            nonlocal found_device
            # Match by service UUID (normal case) OR by device name (Windows paired
            # devices often deliver an empty service_uuids list from the WinRT cache).
            name = (device.name or adv.local_name or "").strip()
            uuid_match = SERVICE_UUID.lower() in [
                str(u).lower() for u in adv.service_uuids
            ]
            name_match = name == "Claude Monitor"
            # Log any named device so scan diagnostics are useful even at INFO level
            if name:
                log.debug(
                    "Scan saw named device: %r (%s) uuid_match=%s",
                    name,
                    device.address,
                    uuid_match,
                )
            if uuid_match or name_match:
                log.debug(
                    "Detected %s (%s) uuid_match=%s name_match=%s uuids=%s",
                    name,
                    device.address,
                    uuid_match,
                    name_match,
                    adv.service_uuids,
                )
                found_device = device
                found_event.set()

        async with BleakScanner(detection_callback=detection_callback):
            try:
                await asyncio.wait_for(found_event.wait(), timeout=SCAN_TIMEOUT)
            except asyncio.TimeoutError:
                return None

        if found_device:
            log.info(
                "Found: %s (%s)",
                found_device.name or "Claude Monitor",
                found_device.address,
            )
        return found_device

    async def _connect(self, device: BLEDevice) -> None:
        """Connect to the display and listen for notifications until disconnected."""
        log.info(
            "Connecting to %s (%s)...", device.name or "Claude Monitor", device.address
        )

        self._force_disconnect = asyncio.Event()
        disconnect_event = asyncio.Event()

        def on_disconnect(client: BleakClient) -> None:
            log.info("BLE disconnected from %s", device.address)
            self._connected = False
            self._client = None
            if self._loop:
                self._loop.call_soon_threadsafe(disconnect_event.set)

        client = BleakClient(
            device,
            disconnected_callback=on_disconnect,
            # pair=True lets the OS complete BLE bonding ("just works", no PIN).
            # Required on Windows; harmless on macOS/Linux.
            pair=True,
            winrt={"use_cached_services": False},
        )

        try:
            await asyncio.wait_for(client.connect(), timeout=CONNECT_TIMEOUT)
        except asyncio.TimeoutError:
            raise Exception(
                f"Connection to {device.address} timed out after {CONNECT_TIMEOUT:.0f}s"
            )

        self._client = client
        self._connected = True
        log.info("BLE connected to %s", device.address)

        try:
            log.info("BLE MTU: %d bytes", client.mtu_size)
        except Exception:
            pass

        await client.start_notify(CHAR_TX_UUID, self._on_notify)

        # Wait until the OS signals a disconnect OR a send error forces one
        await asyncio.wait(
            [
                asyncio.create_task(disconnect_event.wait()),
                asyncio.create_task(self._force_disconnect.wait()),
            ],
            return_when=asyncio.FIRST_COMPLETED,
        )

        try:
            await client.disconnect()
        except Exception:
            pass

    def _on_notify(
        self, characteristic: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Called by bleak when the ESP32 sends a notification (tap, ready, pong)."""
        line = data.decode("utf-8", errors="replace").strip()
        if not line:
            return

        try:
            msg = json.loads(line)
            if self._on_message and self._loop:
                asyncio.run_coroutine_threadsafe(self._on_message(msg), self._loop)
        except json.JSONDecodeError:
            log.debug("Non-JSON from ESP32: %s", line)
