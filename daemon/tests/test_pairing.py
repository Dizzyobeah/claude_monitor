"""Tests for pairing.py — multi-device address storage."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from claude_monitor.pairing import (
    forget_paired_address,
    load_paired_address,
    load_paired_addresses,
    save_paired_address,
)


@pytest.fixture
def temp_state_dir() -> Path:
    """Create a temporary state directory and patch pairing.py to use it."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir)
        with mock.patch("claude_monitor.pairing.STATE_DIR", str(path)):
            with mock.patch("claude_monitor.pairing._PAIRING_FILE", str(path / "device.json")):
                yield path


def test_load_paired_addresses_empty(temp_state_dir: Path) -> None:
    """load_paired_addresses() returns [] when no file exists."""
    assert load_paired_addresses() == []


def test_save_paired_address_creates_file(temp_state_dir: Path) -> None:
    """save_paired_address() creates device.json with new address."""
    save_paired_address("AA:BB:CC:DD:EE:FF")
    addresses = load_paired_addresses()
    assert addresses == ["AA:BB:CC:DD:EE:FF"]
    # Verify JSON format
    with open(temp_state_dir / "device.json") as f:
        data = json.load(f)
    assert data == {"addresses": ["AA:BB:CC:DD:EE:FF"]}


def test_save_paired_address_idempotent(temp_state_dir: Path) -> None:
    """save_paired_address() doesn't duplicate if already present."""
    save_paired_address("AA:BB:CC:DD:EE:FF")
    save_paired_address("AA:BB:CC:DD:EE:FF")
    assert load_paired_addresses() == ["AA:BB:CC:DD:EE:FF"]


def test_save_paired_address_case_insensitive(temp_state_dir: Path) -> None:
    """save_paired_address() treats addresses case-insensitively."""
    save_paired_address("AA:BB:CC:DD:EE:FF")
    save_paired_address("aa:bb:cc:dd:ee:ff")  # Different case
    # Should still be one entry (deduplicated)
    assert len(load_paired_addresses()) == 1


def test_save_paired_address_appends(temp_state_dir: Path) -> None:
    """save_paired_address() appends to existing list."""
    save_paired_address("AA:BB:CC:DD:EE:FF")
    save_paired_address("11:22:33:44:55:66")
    addresses = load_paired_addresses()
    assert len(addresses) == 2
    assert "AA:BB:CC:DD:EE:FF" in addresses
    assert "11:22:33:44:55:66" in addresses


def test_load_paired_address_backward_compat(temp_state_dir: Path) -> None:
    """load_paired_address() returns first address for backward compat."""
    save_paired_address("AA:BB:CC:DD:EE:FF")
    save_paired_address("11:22:33:44:55:66")
    # Old function should return first one
    assert load_paired_address() == "AA:BB:CC:DD:EE:FF"


def test_forget_paired_address_specific(temp_state_dir: Path) -> None:
    """forget_paired_address(address) removes only that entry."""
    save_paired_address("AA:BB:CC:DD:EE:FF")
    save_paired_address("11:22:33:44:55:66")
    forget_paired_address("AA:BB:CC:DD:EE:FF")
    assert load_paired_addresses() == ["11:22:33:44:55:66"]


def test_forget_paired_address_last_one(temp_state_dir: Path) -> None:
    """forget_paired_address() deletes file when removing last device."""
    save_paired_address("AA:BB:CC:DD:EE:FF")
    forget_paired_address("AA:BB:CC:DD:EE:FF")
    assert load_paired_addresses() == []
    assert not (temp_state_dir / "device.json").exists()


def test_forget_paired_address_all(temp_state_dir: Path) -> None:
    """forget_paired_address(None) clears all addresses."""
    save_paired_address("AA:BB:CC:DD:EE:FF")
    save_paired_address("11:22:33:44:55:66")
    forget_paired_address()  # No argument
    assert load_paired_addresses() == []
    assert not (temp_state_dir / "device.json").exists()


def test_forget_paired_address_not_found(temp_state_dir: Path) -> None:
    """forget_paired_address() handles non-existent address gracefully."""
    save_paired_address("AA:BB:CC:DD:EE:FF")
    # Try to remove an address that's not there — should not error
    forget_paired_address("99:88:77:66:55:44")
    # Should still have the original
    assert load_paired_addresses() == ["AA:BB:CC:DD:EE:FF"]


def test_migrate_old_single_address_format(temp_state_dir: Path) -> None:
    """load_paired_addresses() auto-migrates old {"address": "..."} format."""
    # Manually write old format
    device_json = temp_state_dir / "device.json"
    device_json.write_text(json.dumps({"address": "AA:BB:CC:DD:EE:FF"}))

    # Load should migrate and return as list
    addresses = load_paired_addresses()
    assert addresses == ["AA:BB:CC:DD:EE:FF"]

    # File should now be in new format
    data = json.loads(device_json.read_text())
    assert data == {"addresses": ["AA:BB:CC:DD:EE:FF"]}
    assert "address" not in data


def test_migrate_old_format_empty_address(temp_state_dir: Path) -> None:
    """Old format with empty/null address doesn't break migration."""
    device_json = temp_state_dir / "device.json"
    device_json.write_text(json.dumps({"address": ""}))

    # Should return empty list
    assert load_paired_addresses() == []


def test_load_paired_addresses_new_format_preserves(temp_state_dir: Path) -> None:
    """load_paired_addresses() with new format preserves order."""
    device_json = temp_state_dir / "device.json"
    device_json.write_text(
        json.dumps({"addresses": ["AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"]})
    )

    assert load_paired_addresses() == ["AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"]


def test_corrupt_json_file(temp_state_dir: Path) -> None:
    """load_paired_addresses() handles corrupt JSON gracefully."""
    device_json = temp_state_dir / "device.json"
    device_json.write_text("not valid json {{{")

    # Should return empty list instead of crashing
    assert load_paired_addresses() == []


def test_forget_nonexistent_file(temp_state_dir: Path) -> None:
    """forget_paired_address() handles missing file gracefully."""
    # File doesn't exist; should not crash
    forget_paired_address("AA:BB:CC:DD:EE:FF")
    # Should still work (no-op)
    assert load_paired_addresses() == []
