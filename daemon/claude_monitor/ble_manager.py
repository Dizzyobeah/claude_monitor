"""BLE client that auto-discovers and connects to the Claude Monitor ESP32 display."""

import asyncio
import json
import logging
from typing import Callable, Awaitable

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic

log = logging.getLogger(__name__)

# Must match the UUIDs in ble_protocol.h
SERVICE_UUID = "cm010000-cafe-babe-c0de-000000000001"
CHAR_RX_UUID = "cm010001-cafe-babe-c0de-000000000001"  # We write commands here
CHAR_TX_UUID = "cm010002-cafe-babe-c0de-000000000001"  # We receive notifications here

SCAN_TIMEOUT = 5.0      # Seconds to scan for devices
RECONNECT_DELAY = 3.0   # Seconds between reconnection attempts


class BleManager:
    def __init__(self):
        self._client: BleakClient | None = None
        self._connected = False
        self._on_message: Callable[[dict], Awaitable[None]] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def connected(self) -> bool:
        return self._connected

    async def run(self, on_message: Callable[[dict], Awaitable[None]]) -> None:
        """Main loop: scan for display, connect, handle notifications, reconnect."""
        self._on_message = on_message
        self._loop = asyncio.get_running_loop()

        while True:
            try:
                # Scan for the Claude Monitor display
                address = await self._scan()
                if not address:
                    log.info(
                        "No Claude Monitor display found — retrying in %.0fs...",
                        RECONNECT_DELAY,
                    )
                    await asyncio.sleep(RECONNECT_DELAY)
                    continue

                # Connect and stay connected
                await self._connect(address)

            except Exception as e:
                log.warning("BLE error: %s — reconnecting in %.0fs...", e, RECONNECT_DELAY)
                self._connected = False
                self._client = None
                await asyncio.sleep(RECONNECT_DELAY)

    async def send(self, data: str) -> None:
        """Send a JSON message to the ESP32 display via BLE write."""
        if not self._connected or not self._client:
            return
        try:
            payload = data.rstrip("\n").encode("utf-8")
            await self._client.write_gatt_char(CHAR_RX_UUID, payload, response=False)
        except Exception as e:
            log.warning("BLE send error: %s", e)
            self._connected = False

    async def _scan(self) -> str | None:
        """Scan for a BLE device advertising the Claude Monitor service UUID.

        Returns the device address or None.
        """
        log.info("Scanning for Claude Monitor BLE display...")

        devices = await BleakScanner.discover(
            timeout=SCAN_TIMEOUT,
            service_uuids=[SERVICE_UUID],
        )

        for device in devices:
            log.info("Found: %s (%s)", device.name, device.address)
            return device.address

        return None

    async def _connect(self, address: str) -> None:
        """Connect to the display and listen for notifications until disconnected."""
        log.info("Connecting to %s...", address)

        async with BleakClient(
            address,
            disconnected_callback=self._on_disconnect_sync,
        ) as client:
            self._client = client
            self._connected = True
            log.info("BLE connected to %s", address)

            # Request higher MTU for our JSON messages
            try:
                mtu = client.mtu_size
                log.info("BLE MTU: %d bytes", mtu)
            except Exception:
                pass

            # Subscribe to notifications from TX characteristic
            await client.start_notify(CHAR_TX_UUID, self._on_notify)

            # Stay connected until disconnected
            disconnect_event = asyncio.Event()

            def set_disconnect(*_):
                self._loop.call_soon_threadsafe(disconnect_event.set)

            # Override disconnect callback to also set our event
            self._disconnect_setter = set_disconnect

            await disconnect_event.wait()

            self._connected = False
            self._client = None
            log.info("BLE disconnected from %s", address)

    def _on_disconnect_sync(self, client: BleakClient) -> None:
        """Called by bleak from a background thread on disconnect."""
        log.info("BLE disconnect callback fired")
        self._connected = False
        if hasattr(self, "_disconnect_setter"):
            self._disconnect_setter()

    def _on_notify(self, characteristic: BleakGATTCharacteristic, data: bytearray) -> None:
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
