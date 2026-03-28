#pragma once

// OTA (Over-The-Air) firmware update support via BLE.
//
// The ESP32 supports dual-partition OTA: the running firmware lives in one
// partition, and new firmware is written to the other. On success, the boot
// partition is switched and the device reboots into the new firmware.
//
// This module provides:
//   - beginOta(size): prepare to receive firmware of the given size
//   - writeChunk(data, len): write a chunk of firmware data
//   - finishOta(): validate, switch boot partition, and reboot
//   - abortOta(): cancel an in-progress update
//
// The daemon sends firmware in chunks via BLE writes to the RX characteristic.
// The protocol uses a simple command flow:
//   1. {"cmd":"ota_begin","size":123456}
//   2. Raw binary chunks (not JSON) written to RX characteristic
//   3. {"cmd":"ota_end"}  — triggers validation and reboot

#include <Arduino.h>
#include <Update.h>

class OtaManager {
public:
    bool beginOta(size_t firmwareSize) {
        if (_active) abortOta();
        _active = Update.begin(firmwareSize, U_FLASH);
        if (!_active) {
            Serial.printf("[OTA] Begin failed: %s\n", Update.errorString());
        } else {
            Serial.printf("[OTA] Begin OK, expecting %u bytes\n", (unsigned)firmwareSize);
            _received = 0;
            _totalSize = firmwareSize;
        }
        return _active;
    }

    bool writeChunk(const uint8_t* data, size_t len) {
        if (!_active) return false;
        size_t written = Update.write(const_cast<uint8_t*>(data), len);
        if (written != len) {
            Serial.printf("[OTA] Write error: wrote %u of %u\n", (unsigned)written, (unsigned)len);
            abortOta();
            return false;
        }
        _received += len;
        if (_received % 8192 == 0 || _received == _totalSize) {
            Serial.printf("[OTA] Progress: %u / %u bytes (%.0f%%)\n",
                          (unsigned)_received, (unsigned)_totalSize,
                          100.0f * _received / _totalSize);
        }
        return true;
    }

    bool finishOta() {
        if (!_active) return false;
        _active = false;
        if (!Update.end(true)) {
            Serial.printf("[OTA] End failed: %s\n", Update.errorString());
            return false;
        }
        Serial.println("[OTA] Update successful — rebooting...");
        delay(500);
        ESP.restart();
        return true;  // unreachable
    }

    void abortOta() {
        if (_active) {
            Update.abort();
            _active = false;
            Serial.println("[OTA] Aborted");
        }
    }

    bool isActive() const { return _active; }
    size_t received() const { return _received; }
    size_t totalSize() const { return _totalSize; }

private:
    bool _active = false;
    size_t _received = 0;
    size_t _totalSize = 0;
};
