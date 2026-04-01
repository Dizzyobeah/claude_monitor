---
name: firmware-flash
description: Build and flash ESP32 firmware to a board variant, or push an OTA update over BLE. Use when the user wants to flash firmware. (user)
allowed-tools: Bash, Read
---

# Firmware Flash

Build and flash ESP32 firmware via USB or OTA.

## Arguments

- Board environment name (default: `e32r28t`)
- `ota` to push wirelessly over BLE instead of USB

## Instructions

### USB Flash (default)

```bash
cd firmware
pio run -e <env> -t upload
```

Valid environments: `e32r28t`, `cyd_cap`, `cyd_v2`, `cyd_standard`

If the upload fails with a connection error, tell the user to check the USB-C cable and try again -- do not make code changes.

### OTA Flash

1. Build the firmware:
```bash
cd firmware
pio run -e <env>
```

2. Verify the daemon is running and BLE-connected:
```bash
cd daemon
uv run claude-monitor status
```

If not connected, tell the user to start the daemon first.

3. Push the update:
```bash
cd daemon
uv run claude-monitor ota ../firmware/.pio/build/<env>/firmware.bin
```

### After Flashing

Report the result (success/failure) and the flash size from the build output.

## Usage Examples

```
/firmware-flash
/firmware-flash e32r28t
/firmware-flash cyd_cap
/firmware-flash ota
/firmware-flash ota cyd_v2
```
