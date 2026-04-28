"""CLI subcommands for Claude Monitor (status, ota, device)."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_URL = "http://localhost:7483"


def status(base_url: str = DEFAULT_URL) -> None:
    """Query the daemon's /status endpoint and pretty-print it."""
    url = f"{base_url}/status"
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:  # noqa: S310
            data = json.loads(resp.read())
    except (urllib.error.URLError, OSError):
        print("Claude Monitor daemon is not running.", file=sys.stderr)
        sys.exit(1)

    ble = data.get("ble_connected")
    sessions = data.get("sessions", {})

    print(f"BLE connected: {'yes' if ble else 'no' if ble is not None else 'n/a'}")
    print(f"Sessions:       {len(sessions)}")

    if not sessions:
        print("  (none)")
        return

    # Column widths
    sid_w = max(len(s) for s in sessions)
    for sid, info in sessions.items():
        state = info.get("state", "?")
        label = info.get("label", "")
        metrics = info.get("metrics")
        line = f"  {sid:<{sid_w}}  {state:<12} {label}"
        if metrics:
            total_s = sum(metrics.values())
            if total_s > 0:
                mins = int(total_s) // 60
                secs = int(total_s) % 60
                line += f"  ({mins}m{secs:02d}s total)"
        print(line)


def ota(firmware_path: str, base_url: str = DEFAULT_URL) -> None:
    """Push a firmware binary to the ESP32 via the daemon's /ota endpoint."""
    if not os.path.isfile(firmware_path):
        print(f"File not found: {firmware_path}", file=sys.stderr)
        sys.exit(1)

    size = os.path.getsize(firmware_path)
    print(f"Firmware: {firmware_path} ({size:,} bytes)")

    with open(firmware_path, "rb") as f:
        payload = f.read()

    url = f"{base_url}/ota"
    req = urllib.request.Request(  # noqa: S310
        url,
        data=payload,
        headers={
            "Content-Type": "application/octet-stream",
            "X-Firmware-Size": str(size),
        },
        method="POST",
    )

    try:
        print("Uploading to daemon...")
        with urllib.request.urlopen(req, timeout=600) as resp:  # noqa: S310
            result = resp.read().decode()
            print(f"Result: {result}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"OTA failed ({e.code}): {body}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError:
        print("Cannot connect to daemon — is it running?", file=sys.stderr)
        print("Start it with: cd daemon && uv run claude-monitor", file=sys.stderr)
        sys.exit(1)
    except TimeoutError:
        print("OTA timed out — BLE transfer may still be in progress.", file=sys.stderr)
        sys.exit(1)


def device_show() -> None:
    """Print the currently paired device addresses."""
    from .pairing import load_paired_addresses

    addresses = load_paired_addresses()
    if addresses:
        if len(addresses) == 1:
            print(f"Paired device: {addresses[0]}")
        else:
            print(f"Paired devices ({len(addresses)}):")
            for i, addr in enumerate(addresses, 1):
                print(f"  {i}. {addr}")
    else:
        print("Not paired — daemon will scan for any Claude Monitor display on next start.")


def device_forget(address: str | None = None) -> None:
    """Remove a device from the paired list, or clear all if address is None.

    Args:
        address: BLE address to remove. If None, removes all.
    """
    from .pairing import forget_paired_address, load_paired_addresses

    if address:
        # Remove specific address
        addresses_before = load_paired_addresses()
        forget_paired_address(address)
        addresses_after = load_paired_addresses()
        if len(addresses_before) > len(addresses_after):
            print(f"Removed device {address}")
            if addresses_after:
                print(f"Remaining: {len(addresses_after)} device(s)")
            else:
                print("The daemon will scan for any Claude Monitor display on next start.")
        else:
            print(f"Device {address} not found in paired list.")
    else:
        # Clear all
        addresses = load_paired_addresses()
        if not addresses:
            print("No paired devices saved — nothing to forget.")
            return
        forget_paired_address()
        print(f"Cleared {len(addresses)} paired device(s).")
        print("The daemon will scan for any Claude Monitor display on next start.")
