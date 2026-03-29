"""Multi-device BLE manager — connects to multiple Claude Monitor displays.

Wraps multiple BleManager instances with the same interface (connected, send, run)
so the daemon can work with one or many displays without code changes.

All connected devices receive the same state updates (broadcast model).
Messages from any device (tap, ready, overflow) are forwarded to the daemon.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from .ble_manager import BleManager

log = logging.getLogger(__name__)

# Default to 1 device (same behavior as before); set higher for multi-display
DEFAULT_MAX_DEVICES = 1


class BleMultiManager:
    """Manage connections to one or more Claude Monitor ESP32 displays."""

    def __init__(self, max_devices: int = DEFAULT_MAX_DEVICES) -> None:
        self._managers: list[BleManager] = [BleManager() for _ in range(max_devices)]

    @property
    def connected(self) -> bool:
        """True if at least one device is connected."""
        return any(m.connected for m in self._managers)

    @property
    def connected_count(self) -> int:
        """Number of currently connected devices."""
        return sum(1 for m in self._managers if m.connected)

    async def run(
        self, on_message: Callable[[dict[str, Any]], Coroutine[Any, Any, None]]
    ) -> None:
        """Run all device managers concurrently."""
        if len(self._managers) == 1:
            # Single device — run directly (no extra task overhead)
            await self._managers[0].run(on_message)
        else:
            tasks = [
                asyncio.create_task(m.run(on_message), name=f"ble-{i}")
                for i, m in enumerate(self._managers)
            ]
            await asyncio.gather(*tasks)

    async def send(self, data: str) -> None:
        """Broadcast a message to all connected devices."""
        for m in self._managers:
            if m.connected:
                await m.send(data)
