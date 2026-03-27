# Claude Monitor

ESP32-based hardware status display for Claude Code sessions. Shows real-time animated state on a Cheap Yellow Display (CYD), connected via Bluetooth Low Energy. Tap the screen to focus the terminal window that needs your attention.

```
Claude Code hooks --> HTTP POST --> Python daemon --> BLE --> ESP32 display
ESP32 touch       --> BLE --> Python daemon --> AppleScript --> Focus terminal
```

## How it works

1. **ESP32** boots and immediately advertises as `"Claude Monitor"` via BLE GATT
2. **Daemon** (`uv run claude-monitor`) scans for that BLE service, auto-connects
3. **Claude Code hooks** fire on session events, POST to the daemon on `localhost:7483`
4. Daemon maps hook events to display states and pushes them to the ESP32 over BLE
5. Tap the touchscreen to send a focus command back — the daemon activates the correct terminal window via AppleScript

Zero configuration. No WiFi credentials, no IP addresses, no serial port selection.

## Setup

### 1. Flash the ESP32

Requires [PlatformIO](https://platformio.org/install/cli).

```bash
cd firmware
pio run -e e32r28t -t upload
```

Other board variants:

```bash
pio run -e cyd_standard -t upload   # ESP32-2432S028R (ILI9341 + XPT2046)
pio run -e cyd_v2 -t upload         # V2 dual-USB (ST7789 + XPT2046)
pio run -e cyd_cap -t upload        # Capacitive touch (CST820)
```

Power on the display with any USB power source. It will show a pulsing Bluetooth icon while waiting for a connection.

### 2. Install hooks and start the daemon

Requires [uv](https://docs.astral.sh/uv/).

```bash
# Register Claude Code hooks
bash hooks/install.sh

# Start the daemon (auto-discovers display via Bluetooth)
cd daemon
uv run claude-monitor
```

### 3. Use Claude Code

Start any Claude Code session. The display updates automatically.

## Display states

| State | Animation | Trigger |
|-------|-----------|---------|
| IDLE | Slow pulsing blue circle | Session started, waiting for input |
| THINKING | Three orbiting orange dots | User submitted a prompt |
| TOOL_USE | Rotating purple gear | Claude is executing a tool |
| PERMISSION | Red pulsing border + bell | Waiting for permission approval |
| INPUT | Blinking cursor in terminal box | Claude finished, waiting for next prompt |
| ERROR | Red X with shake effect | API error or tool failure |

The RGB LED on the board mirrors the current state color.

## Multi-session support

When multiple Claude Code sessions are active, the display auto-carousels between them every 5 seconds. Sessions that need attention (PERMISSION, INPUT, ERROR) automatically take priority and surface to the front. Session indicator dots in the header show which session is currently displayed.

## Touch interaction

- **Tap**: Sends a focus command to the daemon, which activates the terminal window running the displayed session. If the current session doesn't need attention and multiple sessions exist, the tap also cycles to the next session.

## Architecture

### ESP32 Firmware (`firmware/`)

C++ with PlatformIO, LovyanGFX for display, ESP32 BLE for communication.

- `ble_protocol` — BLE GATT server with custom service UUID, RX characteristic (daemon writes commands) and TX characteristic (ESP32 notifies tap events)
- `display_manager` — Sprite-based 30fps renderer with state-driven animation selection
- `animation/` — One animation class per state, integer-only math with sin/cos lookup table
- `session_store` — Tracks up to 8 concurrent sessions with priority-based carousel
- `touch_handler` — Debounced tap detection
- `board/` — Compile-time board configs for 4 CYD variants

### Python Daemon (`daemon/`)

asyncio-based, installed with `uv run claude-monitor`.

- `ble_manager` — Uses [bleak](https://github.com/hbldh/bleak) to scan, connect, and communicate with the ESP32
- `http_server` — Receives hook event POSTs on `localhost:7483`
- `session_tracker` — Maps hook events to display states
- `terminal_mapper` — Walks the process tree to find which terminal app runs each session
- `window_focus` — Activates terminal windows via AppleScript (supports iTerm2, Terminal, Warp, Ghostty, Kitty, Alacritty, WezTerm)
- `protocol` — Shared JSON message format constants

### Hook Script (`hooks/`)

Single bash script registered for 12 Claude Code events. Reads the hook JSON from stdin and POSTs it to the daemon with TTY/PPID metadata for terminal identification.

## Uninstall

```bash
bash hooks/uninstall.sh
```

## Compatible hardware

Any ESP32-based Cheap Yellow Display with a 240x320 TFT and touch:

| Board | Display | Touch | Build env |
|-------|---------|-------|-----------|
| E32R28T (LCDWIKI) | ILI9341 | XPT2046 | `e32r28t` |
| ESP32-2432S028R | ILI9341 | XPT2046 | `cyd_standard` |
| ESP32-2432S028 V2 | ST7789 | XPT2046 | `cyd_v2` |
| ESP32-2432S028C | ILI9341 | CST820 | `cyd_cap` |
