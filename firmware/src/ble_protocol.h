#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

// Session states matching the Python daemon protocol
enum class SessionState : uint8_t {
    IDLE = 0,
    THINKING,
    TOOL_USE,
    PERMISSION,
    INPUT_NEEDED,
    ERROR,
    DISCONNECTED,
    NUM_STATES
};

const char* stateToString(SessionState state);
SessionState stateFromString(const char* str);
bool stateNeedsAttention(SessionState state);

// Parsed incoming command
struct Command {
    enum Type : uint8_t { NONE, STATE, REMOVE, PING, CONFIG };
    Type type = NONE;
    char sid[6]    = {0};
    SessionState state = SessionState::IDLE;
    char label[21] = {0};
    uint8_t idx    = 0;
    uint8_t total  = 0;
    uint8_t brightness = 255;
};

// BLE UUIDs for Claude Monitor service
// Custom 128-bit UUIDs to avoid conflicts
#define SERVICE_UUID        "c0de0000-cafe-babe-c0de-000000000001"
#define CHAR_RX_UUID        "c0de0001-cafe-babe-c0de-000000000001"  // Daemon writes commands here
#define CHAR_TX_UUID        "c0de0002-cafe-babe-c0de-000000000001"  // ESP32 sends tap events here (notify)

class BleProtocol {
public:
    void begin();
    void update();                  // Call in loop() - processes queued commands
    bool hasCommand();  // protected by _rxMux — see ble_protocol.cpp
    Command takeCommand();

    void sendTap(const char* sid);
    void sendReady();

    bool isConnected() const { return _connected; }

    // Called by BLE callbacks (friend access)
    void _onConnect();
    void _onDisconnect();
    void _onWrite(const uint8_t* data, size_t length);

private:
    BLEServer* _server = nullptr;
    BLECharacteristic* _txChar = nullptr;
    BLECharacteristic* _rxChar = nullptr;

    // Ring buffer for parsed commands — avoids silently dropping commands when
    // the daemon sends a burst (e.g. full-state dump on reconnect).
    static constexpr uint8_t CMD_RING_SIZE = 8;  // power-of-2 keeps wrap cheap
    Command _cmdRing[CMD_RING_SIZE];
    volatile uint8_t _cmdHead = 0;  // consumer index (loop task, core 1)
    volatile uint8_t _cmdTail = 0;  // producer index (BLE task fills via update())

    bool _connected = false;
    bool _justConnected = false;
    bool _advertising = false;  // tracks whether BLE advertising is active

    // Queue for incoming raw BLE data (BLE callback runs on core 0).
    // Protected by _rxMux spinlock — safe across the two ESP32 cores.
    static constexpr size_t RX_BUF_SIZE = 512;
    char _rxBuf[RX_BUF_SIZE];
    size_t _rxLen = 0;
    bool _rxReady = false;
    portMUX_TYPE _rxMux = portMUX_INITIALIZER_UNLOCKED;

    bool parseLine(const char* line);
    void sendJson(const char* json);
};

// Global pointer for BLE callbacks to reach the protocol instance
extern BleProtocol* g_bleProtocol;
