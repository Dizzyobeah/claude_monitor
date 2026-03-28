#include "ble_protocol.h"
#include <BLESecurity.h>

BleProtocol* g_bleProtocol = nullptr;

// ---- BLE Callbacks ----

class ServerCallbacks : public BLEServerCallbacks {
    void onConnect(BLEServer* server) override {
        if (g_bleProtocol) g_bleProtocol->_onConnect();
    }
    void onDisconnect(BLEServer* server) override {
        if (g_bleProtocol) g_bleProtocol->_onDisconnect();
    }
};

class RxCallbacks : public BLECharacteristicCallbacks {
    void onWrite(BLECharacteristic* ch) override {
        if (!g_bleProtocol) return;
        std::string val = ch->getValue();
        if (val.length() > 0) {
            g_bleProtocol->_onWrite((const uint8_t*)val.c_str(), val.length());
        }
    }
};

// ---- State helpers ----

const char* stateToString(SessionState state) {
    switch (state) {
        case SessionState::IDLE:         return "IDLE";
        case SessionState::THINKING:     return "THINKING";
        case SessionState::TOOL_USE:     return "TOOL_USE";
        case SessionState::PERMISSION:   return "PERMISSION";
        case SessionState::INPUT_NEEDED: return "INPUT";
        case SessionState::ERROR:        return "ERROR";
        case SessionState::DISCONNECTED: return "DISCONNECTED";
        default:                         return "UNKNOWN";
    }
}

SessionState stateFromString(const char* str) {
    if (!str) return SessionState::IDLE;
    if (strcmp(str, "THINKING")   == 0) return SessionState::THINKING;
    if (strcmp(str, "TOOL_USE")   == 0) return SessionState::TOOL_USE;
    if (strcmp(str, "PERMISSION") == 0) return SessionState::PERMISSION;
    if (strcmp(str, "INPUT")      == 0) return SessionState::INPUT_NEEDED;
    if (strcmp(str, "ERROR")      == 0) return SessionState::ERROR;
    return SessionState::IDLE;
}

bool stateNeedsAttention(SessionState state) {
    return state == SessionState::PERMISSION ||
           state == SessionState::INPUT_NEEDED ||
           state == SessionState::ERROR;
}

// ---- BleProtocol implementation ----

void BleProtocol::begin() {
    g_bleProtocol = this;

    BLEDevice::init("Claude Monitor");

    // Request a larger MTU so our JSON messages fit in one packet
    BLEDevice::setMTU(256);

    // "Just works" bonding — no PIN, works on Windows/macOS/Linux.
    BLESecurity* security = new BLESecurity();
    security->setAuthenticationMode(ESP_LE_AUTH_REQ_SC_BOND);
    security->setCapability(ESP_IO_CAP_NONE);
    security->setInitEncryptionKey(ESP_BLE_ENC_KEY_MASK | ESP_BLE_ID_KEY_MASK);
    security->setRespEncryptionKey(ESP_BLE_ENC_KEY_MASK | ESP_BLE_ID_KEY_MASK);

    _server = BLEDevice::createServer();
    _server->setCallbacks(new ServerCallbacks());

    // Create service
    BLEService* service = _server->createService(SERVICE_UUID);

    // RX characteristic: daemon writes commands to this
    _rxChar = service->createCharacteristic(
        CHAR_RX_UUID,
        BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR
    );
    _rxChar->setCallbacks(new RxCallbacks());

    // TX characteristic: ESP32 notifies daemon via this
    _txChar = service->createCharacteristic(
        CHAR_TX_UUID,
        BLECharacteristic::PROPERTY_NOTIFY | BLECharacteristic::PROPERTY_READ
    );
    _txChar->addDescriptor(new BLE2902());

    service->start();

    // Start advertising
    BLEAdvertising* adv = BLEDevice::getAdvertising();
    adv->addServiceUUID(SERVICE_UUID);
    // setScanResponse(false) keeps the service UUID in the primary advertisement
    // packet. Windows WinRT only filters on the primary packet, not scan response,
    // so this is required for reliable discovery on Windows.
    adv->setScanResponse(false);
    // Advertising interval: 100ms/150ms — reliably discovered by macOS, Windows,
    // iOS, and Android while using ~3-5x less radio power than the minimum 20ms.
    // Units are 0.625ms: 0xA0 = 100ms, 0xF0 = 150ms.
    adv->setMinInterval(0xA0);
    adv->setMaxInterval(0xF0);
    BLEDevice::startAdvertising();
    _advertising = true;

    Serial.println("BLE advertising as 'Claude Monitor'");
}

void BleProtocol::update() {
    // Safely pull data written by the BLE task (core 0) into a local buffer.
    // portENTER/EXIT_CRITICAL_SAFE work correctly whether called from a task
    // or ISR and handle both single- and dual-core ESP32 variants.
    char local[RX_BUF_SIZE];
    size_t len = 0;
    bool hasData = false;

    portENTER_CRITICAL_SAFE(&_rxMux);
    if (_rxReady) {
        len = _rxLen;
        memcpy(local, _rxBuf, len);
        local[len] = '\0';
        _rxReady = false;
        hasData = true;
    }
    portEXIT_CRITICAL_SAFE(&_rxMux);

    if (hasData) {
        // May contain multiple JSON messages separated by newlines
        char* line = strtok(local, "\n\r");
        while (line) {
            if (strlen(line) > 0) parseLine(line);
            line = strtok(nullptr, "\n\r");
        }
    }

    // Send ready on fresh connection
    if (_justConnected) {
        _justConnected = false;
        sendReady();
    }

    // If disconnected and not already advertising, restart advertising once.
    // Calling startAdvertising() every loop iteration overwhelms the BLE stack
    // and eventually causes it to block, triggering the task watchdog.
    if (!_connected && !_advertising && _server->getConnectedCount() == 0) {
        BLEDevice::startAdvertising();
        _advertising = true;
    }
}

bool BleProtocol::hasCommand() {
    return _cmdHead != _cmdTail;
}

Command BleProtocol::takeCommand() {
    Command c = _cmdRing[_cmdHead % CMD_RING_SIZE];
    _cmdHead = (_cmdHead + 1) % CMD_RING_SIZE;
    return c;
}

void BleProtocol::_onConnect() {
    _connected = true;
    _justConnected = true;
    _advertising = false;  // advertising stops when a client connects
    Serial.println("BLE client connected");
}

void BleProtocol::_onDisconnect() {
    _connected = false;
    _advertising = false;  // mark stale so update() restarts it once
    Serial.println("BLE client disconnected - re-advertising");
}

void BleProtocol::_onWrite(const uint8_t* data, size_t length) {
    if (length >= RX_BUF_SIZE) length = RX_BUF_SIZE - 1;
    portENTER_CRITICAL_SAFE(&_rxMux);
    memcpy(_rxBuf, data, length);
    _rxLen = length;
    _rxReady = true;
    portEXIT_CRITICAL_SAFE(&_rxMux);
}

bool BleProtocol::parseLine(const char* line) {
    JsonDocument doc;
    if (deserializeJson(doc, line)) return false;

    const char* cmd = doc["cmd"];
    if (!cmd) return false;

    Command parsed{};

    if (strcmp(cmd, "state") == 0) {
        parsed.type = Command::STATE;
        const char* sid = doc["sid"];
        if (sid) strncpy(parsed.sid, sid, 5);
        parsed.state = stateFromString(doc["state"]);
        const char* label = doc["label"];
        if (label) strncpy(parsed.label, label, 20);
        parsed.idx   = doc["idx"] | 0;
        parsed.total = doc["total"] | 1;
    } else if (strcmp(cmd, "remove") == 0) {
        parsed.type = Command::REMOVE;
        const char* sid = doc["sid"];
        if (sid) strncpy(parsed.sid, sid, 5);
    } else if (strcmp(cmd, "ping") == 0) {
        parsed.type = Command::PING;
        sendJson("{\"cmd\":\"pong\"}");
        // ping/pong is handled inline — no need to queue it
        return true;
    } else if (strcmp(cmd, "config") == 0) {
        parsed.type = Command::CONFIG;
        parsed.brightness = doc["brightness"] | 255;
    } else {
        return false;
    }

    // Push into ring buffer; if full, drop the oldest entry (overwrite head)
    uint8_t nextTail = (_cmdTail + 1) % CMD_RING_SIZE;
    if (nextTail == _cmdHead) {
        // Ring is full — advance head to make room (oldest command dropped)
        Serial.println("[BLE] Warning: command ring full, dropping oldest command");
        _cmdHead = (_cmdHead + 1) % CMD_RING_SIZE;
    }
    _cmdRing[_cmdTail] = parsed;
    _cmdTail = (_cmdTail + 1) % CMD_RING_SIZE;
    return true;
}

void BleProtocol::sendJson(const char* json) {
    if (!_connected || !_txChar) return;
    _txChar->setValue(json);
    _txChar->notify();
}

void BleProtocol::sendTap(const char* sid) {
    char buf[64];
    snprintf(buf, sizeof(buf), "{\"cmd\":\"tap\",\"sid\":\"%s\"}", sid);
    sendJson(buf);
}

void BleProtocol::sendReady() {
    sendJson("{\"cmd\":\"ready\"}");
}
