#include "ble_protocol.h"
#include <BLESecurity.h>
#include <esp_gap_ble_api.h>

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

// Security callback: display a 6-digit passkey on the CYD screen for the user
// to enter on their computer during BLE pairing.
class SecurityCallbacks : public BLESecurityCallbacks {
    uint32_t onPassKeyRequest() override {
        // Not used in display-only mode
        return 0;
    }
    void onPassKeyNotify(uint32_t passkey) override {
        Serial.printf("[BLE] Passkey for pairing: %06u\n", passkey);
        if (g_bleProtocol) {
            g_bleProtocol->_displayPasskey = passkey;
            g_bleProtocol->_passkeyActive = true;
        }
    }
    bool onConfirmPIN(uint32_t pin) override {
        return true;
    }
    bool onSecurityRequest() override {
        return true;
    }
    void onAuthenticationComplete(esp_ble_auth_cmpl_t cmpl) override {
        Serial.printf("[BLE] Auth complete: %s\n", cmpl.success ? "success" : "failed");
        if (g_bleProtocol) {
            g_bleProtocol->_passkeyActive = false;
            g_bleProtocol->_displayPasskey = 0;
            if (cmpl.success) {
                g_bleProtocol->_onAuthComplete(cmpl.bd_addr);
            }
        }
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

    // Load owner binding from NVS before advertising
    {
        Preferences prefs;
        prefs.begin("claude-mon", true);  // read-only
        _hasOwner = prefs.getBool("owner_set", false);
        if (_hasOwner) {
            prefs.getBytes("owner_addr", _ownerAddr, 6);
            Serial.printf("[BLE] Owner loaded: %02X:%02X:%02X:%02X:%02X:%02X\n",
                _ownerAddr[0], _ownerAddr[1], _ownerAddr[2],
                _ownerAddr[3], _ownerAddr[4], _ownerAddr[5]);
        } else {
            Serial.println("[BLE] No owner — open to first bonder");
        }
        prefs.end();
    }

    BLEDevice::init("Claude Monitor");

    // Request a larger MTU so our JSON messages fit in one packet
    BLEDevice::setMTU(256);

    // Passkey display bonding — ESP32 shows a 6-digit PIN on the CYD screen,
    // user enters it on their computer during pairing. Prevents unauthorized
    // nearby devices from connecting.
    BLEDevice::setSecurityCallbacks(new SecurityCallbacks());
    BLESecurity* security = new BLESecurity();
    security->setAuthenticationMode(ESP_LE_AUTH_REQ_SC_BOND);
    security->setCapability(ESP_IO_CAP_OUT);  // Display-only: show passkey on screen
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

    // Owner binding: save new owner to NVS (deferred from BLE callback).
    if (_claimPending) {
        _claimPending = false;
        memcpy(_ownerAddr, _pendingOwnerAddr, 6);
        _hasOwner = true;
        Preferences prefs;
        prefs.begin("claude-mon", false);
        prefs.putBool("owner_set", true);
        prefs.putBytes("owner_addr", _ownerAddr, 6);
        prefs.end();
        Serial.printf("[BLE] Owner claimed: %02X:%02X:%02X:%02X:%02X:%02X\n",
            _ownerAddr[0], _ownerAddr[1], _ownerAddr[2],
            _ownerAddr[3], _ownerAddr[4], _ownerAddr[5]);
    }

    // Owner binding: kick a non-owner that just connected.
    if (_kickPending) {
        _kickPending = false;
        Serial.println("[BLE] Non-owner connection rejected");
        if (_server) _server->disconnect(0);
    }

    // Send OTA chunk ACK from the main thread (notify isn't safe from BLE callback).
    if (_otaAckPending) {
        _otaAckPending = false;
        char ack[48];
        snprintf(ack, sizeof(ack), "{\"cmd\":\"ota_ack\",\"ok\":%s,\"n\":%u}",
                 _otaAckOk ? "true" : "false",
                 _ota ? (unsigned)_ota->received() : 0u);
        sendJson(ack);
    }

    if (hasData) {
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
    // In OTA mode, write chunks directly to flash from the BLE callback thread.
    // The ACK is sent by update() on the main thread since notify() isn't safe
    // to call from the BLE callback context.
    if (_otaMode && _ota) {
        _otaAckOk = _ota->writeChunk(data, length);
        _otaAckPending = true;
        return;
    }

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
        if (sid) {
            strncpy(parsed.sid, sid, sizeof(parsed.sid) - 1);
            parsed.sid[sizeof(parsed.sid) - 1] = '\0';
        }
        parsed.state = stateFromString(doc["state"]);
        const char* label = doc["label"];
        if (label) {
            strncpy(parsed.label, label, sizeof(parsed.label) - 1);
            parsed.label[sizeof(parsed.label) - 1] = '\0';
        }
        parsed.idx   = doc["idx"] | 0;
        parsed.total = doc["total"] | 1;
    } else if (strcmp(cmd, "remove") == 0) {
        parsed.type = Command::REMOVE;
        const char* sid = doc["sid"];
        if (sid) {
            strncpy(parsed.sid, sid, sizeof(parsed.sid) - 1);
            parsed.sid[sizeof(parsed.sid) - 1] = '\0';
        }
    } else if (strcmp(cmd, "ping") == 0) {
        parsed.type = Command::PING;
        sendJson("{\"cmd\":\"pong\"}");
        // ping/pong is handled inline — no need to queue it
        return true;
    } else if (strcmp(cmd, "config") == 0) {
        parsed.type = Command::CONFIG;
        parsed.brightness = doc["brightness"] | 255;
        parsed.theme = doc["theme"] | 0xFF;  // 0xFF = no change
    } else if (strcmp(cmd, "ota_begin") == 0) {
        if (_ota) {
            uint32_t sz = doc["size"] | 0;
            bool ok = _ota->beginOta(sz);
            _otaMode = ok;
            char ack[48];
            snprintf(ack, sizeof(ack), "{\"cmd\":\"ota_ack\",\"ok\":%s}", ok ? "true" : "false");
            sendJson(ack);
        }
        return true;
    } else if (strcmp(cmd, "ota_end") == 0) {
        _otaMode = false;
        if (_ota) _ota->finishOta();  // reboots on success
        return true;
    } else {
        return false;
    }

    // Push into ring buffer; if full, drop the oldest entry (overwrite head)
    uint8_t nextTail = (_cmdTail + 1) % CMD_RING_SIZE;
    if (nextTail == _cmdHead) {
        // Ring is full — advance head to make room (oldest command dropped)
        Serial.println("[BLE] Warning: command ring full, dropping oldest command");
        _cmdHead = (_cmdHead + 1) % CMD_RING_SIZE;
        // Notify daemon so it can force a full-state resend
        sendJson("{\"cmd\":\"overflow\"}");
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

void BleProtocol::sendDictate(const char* sid) {
    char buf[64];
    snprintf(buf, sizeof(buf), "{\"cmd\":\"dictate\",\"sid\":\"%s\"}", sid);
    sendJson(buf);
}

void BleProtocol::sendReady() {
    sendJson("{\"cmd\":\"ready\"}");
}

void BleProtocol::_onAuthComplete(const uint8_t* addr) {
    // Called from BLE callback (core 0) — only set flags, no blocking NVS or Serial calls.
    if (!_hasOwner) {
        // First successful bond: claim this peer as owner.
        memcpy(_pendingOwnerAddr, addr, 6);
        _claimPending = true;
    } else if (memcmp(_ownerAddr, addr, 6) != 0) {
        // Different peer — schedule a disconnect from the main thread.
        _kickPending = true;
    }
    // Owner address matches: allowed, nothing to do.
}

void BleProtocol::clearOwner() {
    _hasOwner = false;
    _claimPending = false;
    _kickPending = false;
    memset(_ownerAddr, 0, 6);
    memset(_pendingOwnerAddr, 0, 6);
    Preferences prefs;
    prefs.begin("claude-mon", false);
    prefs.remove("owner_set");
    prefs.remove("owner_addr");
    prefs.end();
    // Remove all BLE bonds via esp-idf GAP API (Arduino BLE lib has no wrapper)
    int numBonded = esp_ble_get_bond_device_num();
    if (numBonded > 0) {
        esp_ble_bond_dev_t* devList = (esp_ble_bond_dev_t*)malloc(
            sizeof(esp_ble_bond_dev_t) * numBonded);
        if (devList) {
            esp_ble_get_bond_device_list(&numBonded, devList);
            for (int i = 0; i < numBonded; i++) {
                esp_ble_remove_bond_device(devList[i].bd_addr);
            }
            free(devList);
        }
    }
    Serial.println("[BLE] Owner cleared — open to new bonder after reboot");
}
