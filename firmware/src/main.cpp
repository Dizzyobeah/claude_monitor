// Claude Monitor - ESP32 CYD Status Display for Claude Code
// Communicates with daemon over Bluetooth Low Energy (BLE)
// Just power on - the display advertises as "Claude Monitor"
// and the daemon auto-connects. Zero configuration needed.
// Touch to focus the terminal window needing attention.

#include <Arduino.h>
#include "board/board_config.h"
#include "ble_protocol.h"
#include "session_store.h"
#include "display_manager.h"
#include "touch_handler.h"

static LGFX lcd;
static BleProtocol protocol;
static SessionStore sessions;
static DisplayManager display;
static TouchHandler touch;

void updateLED(SessionState state) {
    switch (state) {
        case SessionState::IDLE:
            digitalWrite(PIN_LED_R, HIGH);
            digitalWrite(PIN_LED_G, HIGH);
            digitalWrite(PIN_LED_B, LOW);   // Blue
            break;
        case SessionState::THINKING:
            digitalWrite(PIN_LED_R, LOW);    // Orange (R+G)
            digitalWrite(PIN_LED_G, LOW);
            digitalWrite(PIN_LED_B, HIGH);
            break;
        case SessionState::TOOL_USE:
            digitalWrite(PIN_LED_R, HIGH);
            digitalWrite(PIN_LED_G, LOW);    // Green
            digitalWrite(PIN_LED_B, HIGH);
            break;
        case SessionState::PERMISSION:
        case SessionState::ERROR:
            digitalWrite(PIN_LED_R, LOW);    // Red
            digitalWrite(PIN_LED_G, HIGH);
            digitalWrite(PIN_LED_B, HIGH);
            break;
        case SessionState::INPUT_NEEDED:
            digitalWrite(PIN_LED_R, HIGH);
            digitalWrite(PIN_LED_G, LOW);    // Cyan
            digitalWrite(PIN_LED_B, LOW);
            break;
        default:
            digitalWrite(PIN_LED_R, HIGH);   // Off
            digitalWrite(PIN_LED_G, HIGH);
            digitalWrite(PIN_LED_B, HIGH);
            break;
    }
}

void setup() {
    Serial.begin(115200);
    Serial.println("\n=== Claude Monitor (BLE) ===");

    // Display first so user sees something immediately
    display.begin(&lcd);

    // Touch
    touch.begin(&lcd);

    // RGB LED off
    pinMode(PIN_LED_R, OUTPUT);
    pinMode(PIN_LED_G, OUTPUT);
    pinMode(PIN_LED_B, OUTPUT);
    digitalWrite(PIN_LED_R, HIGH);
    digitalWrite(PIN_LED_G, HIGH);
    digitalWrite(PIN_LED_B, HIGH);

    // Start BLE (begins advertising immediately)
    protocol.begin();
}

void loop() {
    uint32_t now = millis();

    // BLE event processing
    protocol.update();

    // Process incoming commands
    while (protocol.hasCommand()) {
        Command cmd = protocol.takeCommand();
        switch (cmd.type) {
            case Command::STATE:
                sessions.upsert(cmd.sid, cmd.state, cmd.label);
                break;
            case Command::REMOVE:
                sessions.remove(cmd.sid);
                break;
            case Command::CONFIG:
                lcd.setBrightness(cmd.brightness);
                break;
            default:
                break;
        }
    }

    // Session carousel/housekeeping
    sessions.update(now);

    // Touch -> send focus command
    if (touch.update()) {
        const char* sid = sessions.getDisplayedSid();
        if (sid[0] != '\0' && protocol.isConnected()) {
            protocol.sendTap(sid);
        }
        Session* current = sessions.getDisplayed();
        if (current && !stateNeedsAttention(current->state) && sessions.count() > 1) {
            sessions.cycleNext();
        }
    }

    // LED state
    Session* priority = sessions.getPriority();
    Session* displayed = sessions.getDisplayed();
    if (priority) {
        updateLED(priority->state);
    } else if (displayed) {
        updateLED(displayed->state);
    } else if (!protocol.isConnected()) {
        // Pulse blue while waiting for BLE connection
        bool blink = ((now / 500) % 2) == 0;
        digitalWrite(PIN_LED_B, blink ? LOW : HIGH);
        digitalWrite(PIN_LED_R, HIGH);
        digitalWrite(PIN_LED_G, HIGH);
    } else {
        updateLED(SessionState::DISCONNECTED);
    }

    // Render display
    display.update(now, &sessions, protocol.isConnected());
}
