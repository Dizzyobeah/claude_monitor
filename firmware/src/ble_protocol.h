#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

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
#define SERVICE_UUID        "cm010000-cafe-babe-c0de-000000000001"
#define CHAR_RX_UUID        "cm010001-cafe-babe-c0de-000000000001"  // Daemon writes commands here
#define CHAR_TX_UUID        "cm010002-cafe-babe-c0de-000000000001"  // ESP32 sends tap events here (notify)

class BleProtocol {
public:
    void begin();
    void update();                  // Call in loop() - processes queued commands
    bool hasCommand() const { return _hasCmd; }
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

    Command _cmd;
    bool _hasCmd = false;
    bool _connected = false;
    bool _justConnected = false;

    // Queue for incoming data (BLE callback runs in BLE task, not main loop)
    static constexpr size_t RX_BUF_SIZE = 512;
    char _rxBuf[RX_BUF_SIZE];
    volatile size_t _rxLen = 0;
    volatile bool _rxReady = false;

    bool parseLine(const char* line);
    void sendJson(const char* json);
};

// Global pointer for BLE callbacks to reach the protocol instance
extern BleProtocol* g_bleProtocol;
