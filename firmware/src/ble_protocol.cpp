#include "ble_protocol.h"

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
        String val = ch->getValue();
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
    adv->setScanResponse(true);
    // Helps iPhone connection speed
    adv->setMinPreferred(0x06);
    adv->setMaxPreferred(0x12);
    BLEDevice::startAdvertising();

    Serial.println("BLE advertising as 'Claude Monitor'");
}

void BleProtocol::update() {
    // Process data received from BLE callback
    if (_rxReady) {
        _rxReady = false;
        char local[RX_BUF_SIZE];
        size_t len = _rxLen;
        memcpy(local, _rxBuf, len);
        local[len] = '\0';

        // May contain multiple JSON messages separated by newlines
        char* line = strtok(local, "\n\r");
        while (line) {
            if (strlen(line) > 0 && parseLine(line)) {
                _hasCmd = true;
            }
            line = strtok(nullptr, "\n\r");
        }
    }

    // Send ready on fresh connection
    if (_justConnected) {
        _justConnected = false;
        sendReady();
    }

    // If disconnected, restart advertising
    if (!_connected && _server->getConnectedCount() == 0) {
        BLEDevice::startAdvertising();
    }
}

Command BleProtocol::takeCommand() {
    _hasCmd = false;
    Command c = _cmd;
    _cmd = Command{};
    return c;
}

void BleProtocol::_onConnect() {
    _connected = true;
    _justConnected = true;
    Serial.println("BLE client connected");
}

void BleProtocol::_onDisconnect() {
    _connected = false;
    Serial.println("BLE client disconnected - re-advertising");
    // Restart advertising after disconnect
    BLEDevice::startAdvertising();
}

void BleProtocol::_onWrite(const uint8_t* data, size_t length) {
    if (length >= RX_BUF_SIZE) length = RX_BUF_SIZE - 1;
    memcpy(_rxBuf, data, length);
    _rxLen = length;
    _rxReady = true;
}

bool BleProtocol::parseLine(const char* line) {
    JsonDocument doc;
    if (deserializeJson(doc, line)) return false;

    const char* cmd = doc["cmd"];
    if (!cmd) return false;

    _cmd = Command{};

    if (strcmp(cmd, "state") == 0) {
        _cmd.type = Command::STATE;
        const char* sid = doc["sid"];
        if (sid) strncpy(_cmd.sid, sid, 5);
        _cmd.state = stateFromString(doc["state"]);
        const char* label = doc["label"];
        if (label) strncpy(_cmd.label, label, 20);
        _cmd.idx   = doc["idx"] | 0;
        _cmd.total = doc["total"] | 1;
        return true;
    }
    if (strcmp(cmd, "remove") == 0) {
        _cmd.type = Command::REMOVE;
        const char* sid = doc["sid"];
        if (sid) strncpy(_cmd.sid, sid, 5);
        return true;
    }
    if (strcmp(cmd, "ping") == 0) {
        _cmd.type = Command::PING;
        sendJson("{\"cmd\":\"pong\"}");
        return true;
    }
    if (strcmp(cmd, "config") == 0) {
        _cmd.type = Command::CONFIG;
        _cmd.brightness = doc["brightness"] | 255;
        return true;
    }

    return false;
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
