---
name: esp32-firmware
description: ESP32/Arduino conventions, macro collision avoidance, PlatformIO build commands, and common pitfalls. Use when editing firmware code or debugging build failures. (user)
allowed-tools: Read, Bash, Grep, Glob, Edit, Write, Agent
---

# ESP32 Firmware - Build & Edit Safely

Provides guardrails and conventions for editing ESP32/Arduino firmware in this project.

## Instructions

### Before Any Edit

1. **Locate the firmware source**: `firmware/` directory, PlatformIO project
2. **Check platformio.ini** for environments, board config, and library dependencies
3. **Find PlatformIO binary**: run `which pio` -- never hardcode the path

### Macro Collision Prevention

Arduino.h defines macros that shadow common names. **Never use these as identifiers:**

| Macro | Value | Safe Alternative |
|-------|-------|-----------------|
| `DEFAULT` | 1 | `THEME_DEFAULT`, `MODE_DEFAULT` |
| `HIGH` | 1 | `LEVEL_HIGH`, `PRIORITY_HIGH` |
| `LOW` | 0 | `LEVEL_LOW`, `PRIORITY_LOW` |
| `INPUT` | 1 | `PIN_INPUT`, `MODE_INPUT` |
| `OUTPUT` | 2 | `PIN_OUTPUT`, `MODE_OUTPUT` |
| `LED_BUILTIN` | varies | avoid entirely |
| `A0`-`A7` | varies | use GPIO numbers |

When defining enums, always prefix values with the enum's domain (e.g., `DISPLAY_MODE_DEFAULT`).

### Build-Test Loop

After every firmware edit, run:

```bash
pio run -e esp32dev
```

- Fix all errors before presenting changes to the user
- If build fails, read the **first** error carefully -- cascading errors are noise
- Do NOT make code changes for flash/upload failures -- those are hardware/connection issues

### Common Pitfalls

- **String handling**: Use `String` sparingly -- prefer `char[]` for fixed buffers to avoid heap fragmentation
- **Task stack overflow**: Default FreeRTOS task stack is small. If a task crashes on creation, increase stack size
- **WiFi + BLE coexistence**: Both share the radio. Use `esp_wifi_set_ps(WIFI_PS_MIN_MODEM)` when both are active
- **NVS namespace limit**: 15 chars max for namespace names
- **Partition table**: Check `partitions.csv` if you're running out of flash space

### Library Dependencies

Before adding a new library dependency:
1. Check if it's already in `platformio.ini` under `lib_deps`
2. Verify it supports the ESP32 platform
3. Check for version conflicts with existing deps

## Usage Examples

```
/esp32-firmware
```

Use this skill whenever you're about to edit files in the `firmware/` directory.
