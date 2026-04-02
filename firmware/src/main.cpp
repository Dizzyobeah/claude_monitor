// Claude Monitor - ESP32 CYD Status Display for Claude Code
// Communicates with daemon over Bluetooth Low Energy (BLE)
// Just power on - the display advertises as "Claude Monitor"
// and the daemon auto-connects. Zero configuration needed.
// Touch to focus the terminal window needing attention.

#include <Arduino.h>
#include <Preferences.h>
#include <esp_task_wdt.h>
#include <esp_system.h>
#include "board/board_config.h"
#include "ble_protocol.h"
#include "session_store.h"
#include "display_manager.h"
#include "touch_handler.h"
#include "theme.h"
#include "ota.h"

// Version injected by inject_version.py at build time via -DFW_VERSION
#ifndef FW_VERSION
#define FW_VERSION "dev"
#endif

static LGFX lcd;
static BleProtocol protocol;
static SessionStore sessions;
static DisplayManager display;
static TouchHandler touch;
static Preferences prefs;
static ThemeId activeTheme = ThemeId::THEME_DEFAULT;
static OtaManager ota;

// Last time the RGB LED state was updated. Gated at 500ms to avoid hammering
// digitalWrite on every loop() iteration (which can run thousands of times/sec).
static uint32_t lastLedUpdate = 0;

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
    Serial.printf("\n=== Claude Monitor %s (BLE) ===\n", FW_VERSION);

    // Print reset reason to diagnose reboots
    esp_reset_reason_t reason = esp_reset_reason();
    Serial.printf("[Boot] Reset reason: %d ", (int)reason);
    switch (reason) {
        case ESP_RST_POWERON:  Serial.println("(power-on)"); break;
        case ESP_RST_SW:       Serial.println("(software reset)"); break;
        case ESP_RST_PANIC:    Serial.println("(panic/exception)"); break;
        case ESP_RST_INT_WDT:  Serial.println("(interrupt watchdog)"); break;
        case ESP_RST_TASK_WDT: Serial.println("(task watchdog)"); break;
        case ESP_RST_WDT:      Serial.println("(other watchdog)"); break;
        case ESP_RST_BROWNOUT: Serial.println("(brownout)"); break;
        default:               Serial.println("(unknown)"); break;
    }
    Serial.printf("[Boot] Free heap: %u bytes\n", (unsigned)ESP.getFreeHeap());

    // Load persisted theme from NVS
    prefs.begin("claude-mon", false);
    uint8_t savedTheme = prefs.getUChar("theme", 0);
    if (savedTheme < NUM_THEMES) {
        activeTheme = static_cast<ThemeId>(savedTheme);
    }
    prefs.end();
    Serial.printf("[Boot] Theme: %u\n", static_cast<unsigned>(activeTheme));

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
    protocol.setOtaManager(&ota);
    protocol.begin();

    // Hardware watchdog: reset the device if loop() stalls for more than 15 seconds.
    // This recovers from BLE stack hangs or display deadlocks without manual intervention.
    // ESP-IDF v5 API: esp_task_wdt_init takes a config struct, not (timeout, panic).
    const esp_task_wdt_config_t wdt_cfg = {
        .timeout_ms = 15000,
        .idle_core_mask = 0,       // Don't watch idle tasks
        .trigger_panic = true,
    };
    esp_task_wdt_init(&wdt_cfg);
    esp_task_wdt_add(NULL);        // Subscribe the current (loop) task
    Serial.println("Watchdog armed (15s timeout)");
}

// Debug: log loop phases that exceed this threshold (ms)
static constexpr uint32_t LOOP_WARN_MS = 100;
static uint32_t loopCount = 0;
static uint32_t lastLoopReport = 0;

void loop() {
    uint32_t now = millis();
    uint32_t loopStart = now;
    loopCount++;

    // Print once on first loop iteration to confirm loop() is running
    static bool firstLoop = true;
    if (firstLoop) {
        firstLoop = false;
        Serial.printf("[Loop] First iteration at %ums, stack high water: %u bytes free\n",
                      now, (unsigned)uxTaskGetStackHighWaterMark(NULL));
    }

    // Reset watchdog — proves loop() is alive to the hardware timer
    esp_task_wdt_reset();

    // --- BLE event processing ---
    uint32_t t0 = millis();
    protocol.update();
    uint32_t t1 = millis();
    if (t1 - t0 > LOOP_WARN_MS) Serial.printf("[SLOW] BLE update: %ums\n", t1 - t0);

    // --- Process incoming commands ---
    uint8_t cmdCount = 0;
    while (protocol.hasCommand()) {
        cmdCount++;
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
                if (cmd.theme < NUM_THEMES) {
                    activeTheme = static_cast<ThemeId>(cmd.theme);
                    prefs.begin("claude-mon", false);
                    prefs.putUChar("theme", cmd.theme);
                    prefs.end();
                    Serial.printf("[Config] Theme changed to %u\n", cmd.theme);
                }
                break;
            case Command::OTA_BEGIN:
            case Command::OTA_END:
                // Handled directly by BLE protocol (OTA mode)
                break;
            default:
                break;
        }
    }
    uint32_t t2 = millis();
    if (t2 - t1 > LOOP_WARN_MS) Serial.printf("[SLOW] Commands (%u): %ums\n", cmdCount, t2 - t1);

    // --- Session carousel/housekeeping ---
    sessions.update(now);
    uint32_t t3 = millis();
    if (t3 - t2 > LOOP_WARN_MS) Serial.printf("[SLOW] Sessions: %ums\n", t3 - t2);

    // --- Touch ---
    // Footer arrow touch zones for session navigation:
    //   Left  arrow: x < 50, y >= footerTop (240)
    //   Right arrow: x > 190, y >= footerTop (240)
    //   Centre/animation zone: existing tap/long-press behaviour
    static constexpr int16_t FOOTER_TOP = 240;  // HEADER_H + ANIM_H
    static constexpr int16_t ARROW_ZONE_W = 50;

    TouchEvent touchEvt = touch.update();
    if (touchEvt == TouchEvent::TAP) {
        int16_t tx = touch.lastX();
        int16_t ty = touch.lastY();

        if (ty >= FOOTER_TOP && sessions.count() > 1) {
            // Tap in footer zone — check for arrow navigation
            if (tx < ARROW_ZONE_W) {
                sessions.cyclePrev();
            } else if (tx > SCREEN_W - ARROW_ZONE_W) {
                sessions.cycleNext();
            } else {
                // Centre footer tap — send tap to daemon
                const char* sid = sessions.getDisplayedSid();
                if (sid[0] != '\0' && protocol.isConnected()) {
                    protocol.sendTap(sid);
                }
            }
        } else {
            // Animation zone tap — send tap + cycle if not attention-needing
            const char* sid = sessions.getDisplayedSid();
            if (sid[0] != '\0' && protocol.isConnected()) {
                protocol.sendTap(sid);
            }
            Session* current = sessions.getDisplayed();
            if (current && !stateNeedsAttention(current->state) && sessions.count() > 1) {
                sessions.cycleNext();
            }
        }
    } else if (touchEvt == TouchEvent::LONG_PRESS) {
        const char* sid = sessions.getDisplayedSid();
        if (sid[0] != '\0' && protocol.isConnected()) {
            protocol.sendDictate(sid);
        }
    }
    uint32_t t4 = millis();
    if (t4 - t3 > LOOP_WARN_MS) Serial.printf("[SLOW] Touch: %ums\n", t4 - t3);

    // --- LED state ---
    // Override LED to magenta during long-press hold for visual feedback
    if (touch.isLongPressActive()) {
        digitalWrite(PIN_LED_R, LOW);   // Magenta (R+B)
        digitalWrite(PIN_LED_G, HIGH);
        digitalWrite(PIN_LED_B, LOW);
    } else
    if (now - lastLedUpdate >= 500) {
        lastLedUpdate = now;
        Session* priority = sessions.getPriority();
        Session* displayed = sessions.getDisplayed();
        if (priority) {
            updateLED(priority->state);
        } else if (displayed) {
            updateLED(displayed->state);
        } else if (!protocol.isConnected()) {
            static bool blinkState = false;
            blinkState = !blinkState;
            digitalWrite(PIN_LED_B, blinkState ? LOW : HIGH);
            digitalWrite(PIN_LED_R, HIGH);
            digitalWrite(PIN_LED_G, HIGH);
        } else {
            updateLED(SessionState::DISCONNECTED);
        }
    }
    uint32_t t5 = millis();

    // --- Render display ---
    // Show passkey overlay during BLE pairing, otherwise normal display
    if (protocol.isPasskeyActive()) {
        display.drawPasskeyOverlay(protocol.getPasskey());
    } else {
        display.update(now, &sessions, protocol.isConnected());
    }
    uint32_t t6 = millis();
    if (t6 - t5 > LOOP_WARN_MS) Serial.printf("[SLOW] Display: %ums\n", t6 - t5);

    // --- Total loop time ---
    uint32_t loopTime = t6 - loopStart;
    if (loopTime > LOOP_WARN_MS) {
        Serial.printf("[SLOW] Loop total: %ums (ble=%u cmd=%u sess=%u touch=%u led=%u disp=%u)\n",
                      loopTime, t1-t0, t2-t1, t3-t2, t4-t3, t5-t4, t6-t5);
    }

    // Periodic status report every 30 seconds
    if (now - lastLoopReport >= 30000) {
        lastLoopReport = now;
        Serial.printf("[Status] uptime=%us loops=%u heap=%u sessions=%u ble=%s\n",
                      now / 1000, loopCount, (unsigned)ESP.getFreeHeap(),
                      sessions.count(), protocol.isConnected() ? "yes" : "no");
    }
}
