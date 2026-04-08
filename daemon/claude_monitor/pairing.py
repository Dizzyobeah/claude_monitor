"""Persistent pairing state: remembers which BLE device address belongs to this computer."""

from __future__ import annotations

import json
import logging
import os

log = logging.getLogger(__name__)

# Reuse the same state dir as the lock file
STATE_DIR = os.path.join(os.path.expanduser("~"), ".local", "state", "claude-monitor")
_PAIRING_FILE = os.path.join(STATE_DIR, "device.json")


def load_paired_address() -> str | None:
    """Return the saved BLE device address, or None if not paired yet."""
    try:
        with open(_PAIRING_FILE) as f:
            data = json.load(f)
        address = data.get("address")
        if address:
            return str(address)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return None


def save_paired_address(address: str) -> None:
    """Persist the BLE device address so future scans target only this device."""
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        with open(_PAIRING_FILE, "w") as f:
            json.dump({"address": address}, f)
        log.info("Paired to device %s — saved to %s", address, _PAIRING_FILE)
    except OSError as e:
        log.warning("Could not save paired device address: %s", e)


def forget_paired_address() -> None:
    """Delete the saved pairing so the next scan will connect to any Claude Monitor."""
    try:
        os.remove(_PAIRING_FILE)
        log.info("Paired device address cleared")
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warning("Could not remove pairing file: %s", e)
