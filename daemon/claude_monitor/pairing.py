"""Persistent pairing state: remembers which BLE device addresses belong to this computer."""

from __future__ import annotations

import json
import logging
import os

log = logging.getLogger(__name__)

# Reuse the same state dir as the lock file
STATE_DIR = os.path.join(os.path.expanduser("~"), ".local", "state", "claude-monitor")
_PAIRING_FILE = os.path.join(STATE_DIR, "device.json")


def load_paired_addresses() -> list[str]:
    """Return the list of saved BLE device addresses. Returns [] if no devices are paired.

    Auto-migrates old single-address format {"address": "..."} to new list format
    {"addresses": [...]}, writing back the new format on successful migration.
    """
    try:
        with open(_PAIRING_FILE) as f:
            data = json.load(f)

        # New format: list of addresses
        if "addresses" in data:
            addresses = data.get("addresses", [])
            return [str(a) for a in addresses if a]

        # Old format: single address — migrate to new format
        if "address" in data:
            old_address = data.get("address")
            if old_address:
                old_address_str = str(old_address)
                log.info("Migrating old pairing format to list-based storage")
                # Write back in new format so migration only happens once
                os.makedirs(STATE_DIR, exist_ok=True)
                try:
                    with open(_PAIRING_FILE, "w") as f:
                        json.dump({"addresses": [old_address_str]}, f)
                except OSError as e:
                    log.warning("Could not migrate pairing file: %s", e)
                return [old_address_str]

    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return []


def load_paired_address() -> str | None:
    """Deprecated: return first address from list for backward compatibility.

    New code should use load_paired_addresses() instead.
    """
    addresses = load_paired_addresses()
    return addresses[0] if addresses else None


def save_paired_address(address: str) -> None:
    """Append a BLE device address to the known devices list if not already present (idempotent).

    If the file doesn't exist, creates it with a single-entry list.
    """
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        addresses = load_paired_addresses()
        # Normalize case for comparison
        normalized = address.lower()
        if not any(a.lower() == normalized for a in addresses):
            addresses.append(address)
            with open(_PAIRING_FILE, "w") as f:
                json.dump({"addresses": addresses}, f)
            log.info("Paired to device %s — saved to %s", address, _PAIRING_FILE)
        else:
            log.debug("Device %s already in paired list", address)
    except OSError as e:
        log.warning("Could not save paired device address: %s", e)


def forget_paired_address(address: str | None = None) -> None:
    """Remove a device from the paired list, or clear all if address is None.

    Args:
        address: BLE address to remove. If None, removes all (full forget).
    """
    try:
        if address is None:
            # Clear all
            os.remove(_PAIRING_FILE)
            log.info("All paired device addresses cleared")
        else:
            # Remove specific address
            addresses = load_paired_addresses()
            normalized = address.lower()
            updated = [a for a in addresses if a.lower() != normalized]
            if len(updated) < len(addresses):
                if updated:
                    with open(_PAIRING_FILE, "w") as f:
                        json.dump({"addresses": updated}, f)
                    log.info("Removed device %s from paired list", address)
                else:
                    # Last device was removed — delete the file
                    os.remove(_PAIRING_FILE)
                    log.info("Removed device %s; no devices paired", address)
            else:
                log.debug("Device %s not found in paired list", address)
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warning("Could not update pairing file: %s", e)
